"""Change → outbox rows → Gmail/Calendar (D5).

Rows are queued inside the email's transaction, together with the state they reflect and "processed".
`flush` sends them afterwards, in order, marking each one sent. A row that fails stops the flush and is
retried on the next poll, so nothing is sent twice and nothing is dropped.
"""

import json
import logging
from datetime import datetime

from butler import render
from butler.config import Settings
from butler.gateway import Email, Gateway
from butler.store import Store, headcount, status

log = logging.getLogger("butler")


def approve(store: Store, settings: Settings, dinner_id: int) -> list[str]:
    """H2: the Dinner goes live. Queues the calendar event (Host only) and one private invite per Guest."""
    store.update_dinner(dinner_id, status="active", title=render.title(store.dinner(dinner_id)))
    dinner, notes, guests = store.dinner(dinner_id), store.notes(dinner_id), store.guests(dinner_id)
    change_id = store.add_change(dinner_id, "approve")
    start = datetime.fromisoformat(dinner["start_at"])
    store.queue("calendar", dinner["host_email"], {
        "kind": "create_event",
        "dinner_id": dinner_id,
        "title": dinner["title"],
        "start": start.isoformat(),
        "end": (start + render.EVENT_LENGTH).isoformat(),
        "place": dinner["place"],
        "description": description(store, settings, dinner_id),
    }, change_id=change_id)
    subject, body = render.invite(dinner, notes)
    for guest in guests:
        store.queue("guest", guest["email"], {"kind": "invite", "dinner_id": dinner_id, "subject": subject,
                                              "body": body}, change_id=change_id)
    return [guest["email"] for guest in guests]


def description(store: Store, settings: Settings, dinner_id: int) -> str:
    dinner, guests = store.dinner(dinner_id), store.guests(dinner_id)
    names = [render.guest_label(guest) for guest in guests if status(guest) == "attending"]
    return render.description(dinner, store.notes(dinner_id), names, headcount(guests), settings.butler_email)


def update_description(store: Store, settings: Settings, dinner_id: int, change_id: int) -> None:
    store.queue("calendar", "description", {"kind": "update_description", "dinner_id": dinner_id,
                                            "description": description(store, settings, dinner_id)},
                change_id=change_id)


def rsvp(store: Store, settings: Settings, dinner_id: int, before) -> None:
    """A Guest's email may have changed their RSVP (G1–G4): fan the net change out once, however many
    record_rsvp calls it took. Calendar first (add, remove, or re-add; only an add emails anyone, and only that
    Guest), then the description if Headcount moved, then the Host's private notice."""
    email = before["email"]
    after = store.guest(dinner_id, email)
    if after["on_calendar"] and not before["on_calendar"]:
        kind = "add_attendee"
    elif before["on_calendar"] and not after["on_calendar"]:
        kind = "remove_attendee"
    elif after["on_calendar"] and before["calendar_answer"] == "declined" and after["calendar_answer"] != "declined":
        kind = "readd_attendee"  # declined on the calendar, then said yes by email: one fresh invite (D13)
    else:
        kind = None
        if after["calendar_answer"] != before["calendar_answer"]:  # "no, wait, yes": still on it, answer unknown
            store.update_guest(dinner_id, email, calendar_answer=before["calendar_answer"])
            after = store.guest(dinner_id, email)
    if dict(after) == dict(before):
        return

    was, now = status(before), status(after)
    change_id = store.add_change(dinner_id, "rsvp", {"guest": email, "via": "email", "was": was, "now": now})
    if kind:
        store.queue("calendar", email, {"kind": kind, "dinner_id": dinner_id}, change_id=change_id)
    if (was == "attending") != (now == "attending") or now == "attending" and before["plus_ones"] != after["plus_ones"]:
        update_description(store, settings, dinner_id, change_id)  # Headcount or who's coming moved
    if was != now or any(before[f] != after[f] for f in ("plus_ones", "dietary_needs", "guest_note")):
        dinner = store.dinner(dinner_id)
        store.queue("host", dinner["host_email"], {
            "kind": "host_notice",
            "dinner_id": dinner_id,
            "body": render.host_notice(after, was, now, headcount(store.guests(dinner_id))),
            "reply_to": store.last_from(dinner["host_thread_id"], dinner["host_email"]),
        }, change_id=change_id)


def reply(store: Store, email: Email, channel: str, body: str) -> None:
    """Butler's answer to an inbound email, to its sender only, in the same thread."""
    store.queue(channel, email.sender, {"kind": "reply", "body": body}, message_id=email.message_id)


def flush(gateway: Gateway, store: Store) -> None:
    for row in store.pending():
        payload = json.loads(row["payload"])
        try:
            sent_id, record = _send(gateway, store, row, payload)
        except Exception:
            log.exception("sending outbox row %s (%s to %s) failed; retrying next poll", row["id"], payload["kind"],
                          row["recipient"])
            return
        with store.transaction():
            record(store)
            store.mark_sent(row["id"], sent_id)
        log.info("sent %s to %s", payload["kind"], row["recipient"])


def _send(gateway: Gateway, store: Store, row, payload: dict):
    """Makes the Arcade call. Returns the sent id and what to record about it, committed with "sent"."""
    kind, dinner_id, recipient = payload["kind"], payload.get("dinner_id"), row["recipient"]
    if kind == "reply":
        return gateway.reply(row["message_id"], payload["body"]).message_id, _nothing
    if kind == "host_notice":
        return gateway.reply(payload["reply_to"], payload["body"]).message_id, _nothing
    # Calendar rows read the event id when they're sent: it may have been created after they were queued.
    event_id = store.dinner(dinner_id)["calendar_event_id"] if dinner_id else None
    if kind == "add_attendee":
        gateway.add_attendee(event_id, recipient)
        return None, _nothing
    if kind == "remove_attendee":
        gateway.remove_attendee(event_id, recipient)
        return None, _nothing
    if kind == "readd_attendee":  # removing first resets their calendar answer; a retry repeats both, harmlessly
        gateway.remove_attendee(event_id, recipient)
        gateway.add_attendee(event_id, recipient)
        return None, _nothing
    if kind == "update_description":
        gateway.update_event(event_id, description=payload["description"])
        return None, _nothing
    if kind == "create_event":
        event_id = gateway.create_event(
            payload["title"], datetime.fromisoformat(payload["start"]), datetime.fromisoformat(payload["end"]),
            payload["place"], payload["description"], recipient,
        )
        return event_id, lambda store: store.update_dinner(dinner_id, calendar_event_id=event_id)
    if kind == "invite":
        sent = gateway.send(recipient, payload["subject"], payload["body"])
        return sent.message_id, lambda store: store.update_guest(dinner_id, recipient, guest_thread_id=sent.thread_id)
    raise ValueError(f"unknown outbox row kind {kind!r}")


def _nothing(store: Store) -> None:
    pass
