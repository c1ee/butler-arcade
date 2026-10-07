"""Poll loop: every POLL_SECONDS, read Butler's inbox, handle each new email once, then tick.

Run: `uv run butler` (or `uv run butler --once` for a single poll).
"""

import argparse
import logging
import time
from dataclasses import replace
from datetime import UTC, datetime

import anthropic

from butler import agent, config, effects, gate, render, sync, tools
from butler.config import Settings
from butler.gateway import Email, Gateway
from butler.router import Route, route
from butler.store import LIVE, Store

log = logging.getLogger("butler")

# Each poll re-reads this many seconds before the last one, in case Gmail indexes an email late.
# Dedupe by message id makes the overlap harmless.
OVERLAP_SECONDS = 120


def poll_once(gateway: Gateway, claude, store: Store, settings: Settings, now: datetime) -> None:
    effects.flush(gateway, store)  # anything a failed send left behind
    started = int(now.timestamp())
    since = store.poll_cursor() or started  # first run: only email from now on
    for email in gateway.search_inbox(after=since - OVERLAP_SECONDS):
        if store.is_processed(email.message_id):
            continue
        r = route(email, store, settings)
        log.info(describe(email, r))
        handle(email, r, gateway, claude, store, settings, now)
    with store.transaction():
        store.set_poll_cursor(started)


def handle(email: Email, r: Route, gateway: Gateway, claude, store: Store, settings: Settings, now: datetime) -> None:
    """One email, exactly once: its state changes, outbox rows (reply included), and "processed" commit together;
    sending happens after (D5). A failure before the commit leaves the email to be retried on the next poll."""
    dinner = store.dinner(r.dinner_id) if r.dinner_id else None
    if not converses(r, dinner):
        with store.transaction():
            store.mark_processed(email, r, now)
        return

    earlier = agent.history(gateway, email, r.channel, settings.butler_email)
    gated = gate.should_speak(claude, settings, store, r.dinner_id, email, r.role, earlier) \
        if r.channel == "group_thread" else None
    host_live = r.role == "host" and dinner is not None and dinner["status"] in LIVE
    with store.transaction():
        if gated:
            decision, shown = gated
            store.add_trace(email.message_id, 0, "gate", shown, decision.model_dump())
            if not decision.speak:
                store.mark_processed(email, r, now)
                log.info("silent in the Group thread: %s", decision.reason)
                return
        if dinner is None:  # the Host's first email starts a draft (H1)
            dinner_id = store.create_dinner(host_email=email.sender, host_name=email.sender_name or None,
                                            host_thread_id=email.thread_id)
            r = replace(r, dinner_id=dinner_id)
        if r.role == "guest":
            if email.sender_name:
                store.update_guest(r.dinner_id, email.sender, name=email.sender_name)
            before = store.guest(r.dinner_id, email.sender)
        elif host_live:
            before = effects.snapshot(store, r.dinner_id)
        ctx = tools.Ctx(store, settings, r.dinner_id, email.sender, now, gateway, email.message_id)
        body = agent.answer(claude, settings.model, ctx, agent.Turn(email, r.role, r.channel, earlier))
        update = None
        if r.role == "guest":
            effects.rsvp(store, settings, r.dinner_id, before)
            effects.join_group(store, settings, r.dinner_id, now)
        elif host_live:
            update = effects.host_changes(store, settings, r.dinner_id, before, in_group=r.channel == "group_thread")
            if r.channel == "host_thread":
                tools.lapse_cancel(store, r.dinner_id, email.message_id)
        dinner = store.dinner(r.dinner_id)
        if r.channel == "group_thread":
            if update:  # the Host changed the Dinner from the group: the update rides on this reply
                body = f"{body}\n\n{update}"
            effects.group_reply(store, email, r.dinner_id, render.sign(body, dinner))
        elif r.role == "guest":
            effects.reply(store, email, "guest", render.sign(body, dinner))
        else:
            if preview := tools.show_draft(store, r.dinner_id):
                body = f"{body}\n\n{preview}"
            effects.reply(store, email, "host", render.sign(body))
        store.mark_processed(email, r, now)
    log.info("replied to %s (Dinner %s now %s)", email.sender, r.dinner_id, store.dinner(r.dinner_id)["status"])
    effects.flush(gateway, store)


def converses(r: Route, dinner) -> bool:
    """Whether this email goes to the tool loop: the Host thread, a Guest in their own thread while the Dinner is
    live, or anyone in the Group thread (the should_speak gate decides there)."""
    if r.skipped:
        return False
    if r.channel == "host_thread":
        return True  # the router already skipped Dinners that are over
    if dinner["status"] not in LIVE:
        return False
    return r.channel == "group_thread" or r.channel == "guest_thread" and r.role == "guest"


def tick(gateway: Gateway, store: Store, settings: Settings, now: datetime) -> None:
    with store.transaction():
        for dinner_id in store.close_finished(now):
            log.info("Dinner %s closed: an hour past its start", dinner_id)
    sync.sync(gateway, store, settings, now)
    effects.flush(gateway, store)


def describe(email: Email, r: Route) -> str:
    where = f"Dinner {r.dinner_id}" if r.dinner_id else "new Dinner" if r.channel else "no Dinner"
    outcome = f"skipped ({r.skipped})" if r.skipped else f"{where}, {r.channel}, {r.role}"
    return f"{email.message_id} from {email.sender} {email.subject[:60]!r} → {outcome}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Butler: polls its inbox and handles Dinner email.")
    parser.add_argument("--once", action="store_true", help="poll once and exit")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    for noisy in ("httpx", "httpx2"):  # every Arcade and Claude request
        logging.getLogger(noisy).setLevel(logging.WARNING)

    settings = config.load()
    store = Store(settings.db_path)
    gateway = Gateway(settings)
    claude = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    log.info("Butler %s polling every %ss (Host %s)", settings.butler_email, settings.poll_seconds, settings.host_email)
    try:
        while True:
            now = datetime.now(UTC)
            try:
                poll_once(gateway, claude, store, settings, now)
                tick(gateway, store, settings, now)
            except Exception:
                log.exception("poll failed; retrying next poll")
            if args.once:
                break
            time.sleep(settings.poll_seconds)
    except KeyboardInterrupt:
        log.info("stopped")


if __name__ == "__main__":
    main()
