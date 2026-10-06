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
from butler.store import Store

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
        "description": render.description(dinner, notes, [], 0, settings.butler_email),
    }, change_id=change_id)
    subject, body = render.invite(dinner, notes)
    for guest in guests:
        store.queue("guest", guest["email"], {"kind": "invite", "dinner_id": dinner_id, "subject": subject,
                                              "body": body}, change_id=change_id)
    return [guest["email"] for guest in guests]


def reply(store: Store, email: Email, channel: str, body: str) -> None:
    """Butler's answer to an inbound email, to its sender only, in the same thread."""
    store.queue(channel, email.sender, {"kind": "reply", "body": body}, message_id=email.message_id)


def flush(gateway: Gateway, store: Store) -> None:
    for row in store.pending():
        payload = json.loads(row["payload"])
        try:
            sent_id, record = _send(gateway, row, payload)
        except Exception:
            log.exception("sending outbox row %s (%s to %s) failed; retrying next poll", row["id"], payload["kind"],
                          row["recipient"])
            return
        with store.transaction():
            record(store)
            store.mark_sent(row["id"], sent_id)
        log.info("sent %s to %s", payload["kind"], row["recipient"])


def _send(gateway: Gateway, row, payload: dict):
    """Makes the Arcade call. Returns the sent id and what to record about it, committed with "sent"."""
    kind, dinner_id, recipient = payload["kind"], payload.get("dinner_id"), row["recipient"]
    if kind == "reply":
        return gateway.reply(row["message_id"], payload["body"]).message_id, lambda store: None
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
