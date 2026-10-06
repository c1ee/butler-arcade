"""Poll loop: every POLL_SECONDS, read Butler's inbox, handle each new email once, then tick.

Run: `uv run butler` (or `uv run butler --once` for a single poll).
"""

import argparse
import logging
import time
from datetime import UTC, datetime

from butler import config
from butler.config import Settings
from butler.gateway import Email, Gateway
from butler.router import Route, route
from butler.store import Store

log = logging.getLogger("butler")

# Each poll re-reads this many seconds before the last one, in case Gmail indexes an email late.
# Dedupe by message id makes the overlap harmless.
OVERLAP_SECONDS = 120


def poll_once(gateway: Gateway, store: Store, settings: Settings, now: datetime) -> None:
    started = int(now.timestamp())
    since = store.poll_cursor() or started  # first run: only email from now on
    for email in gateway.search_inbox(after=since - OVERLAP_SECONDS):
        if store.is_processed(email.message_id):
            continue
        r = route(email, store, settings)
        log.info(describe(email, r))
        with store.transaction():
            store.mark_processed(email, r, now)
    with store.transaction():
        store.set_poll_cursor(started)


def tick(gateway: Gateway, store: Store, now: datetime) -> None:
    with store.transaction():
        for dinner_id in store.close_finished(now):
            log.info("Dinner %s closed: an hour past its start", dinner_id)


def describe(email: Email, r: Route) -> str:
    where = f"Dinner {r.dinner_id}" if r.dinner_id else "new Dinner" if r.channel else "no Dinner"
    outcome = f"skipped ({r.skipped})" if r.skipped else f"{where}, {r.channel}, {r.role}"
    return f"{email.message_id} from {email.sender} {email.subject[:60]!r} → {outcome}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Butler: polls its inbox and handles Dinner email.")
    parser.add_argument("--once", action="store_true", help="poll once and exit")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    settings = config.load()
    store = Store(settings.db_path)
    gateway = Gateway(settings)
    log.info("Butler %s polling every %ss (Host %s)", settings.butler_email, config.POLL_SECONDS, settings.host_email)
    try:
        while True:
            now = datetime.now(UTC)
            try:
                poll_once(gateway, store, settings, now)
                tick(gateway, store, now)
            except Exception:
                log.exception("poll failed; retrying next poll")
            if args.once:
                break
            time.sleep(config.POLL_SECONDS)
    except KeyboardInterrupt:
        log.info("stopped")


if __name__ == "__main__":
    main()
