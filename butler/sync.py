"""Per-poll calendar read: the Calendar event decides who's coming (D13, G7).

Guests answer the invite's Yes/No/Maybe buttons without telling Butler. Every poll reads each live Dinner's
event, diffs attendee answers against the last snapshot, and re-renders the description when Headcount moves.
Calendar answers email nobody: no Host notice, nothing to the Guest. Plus-ones stay email only ("+N" ignored).
"""

import logging

from butler import effects
from butler.config import Settings
from butler.gateway import Event, Gateway
from butler.store import Store, status

log = logging.getLogger("butler")


def sync(gateway: Gateway, store: Store, settings: Settings) -> None:
    if store.pending():
        return  # a queued attendee add or removal would read as a calendar answer; flush first, sync next poll
    for dinner in store.live_dinners():
        if dinner["calendar_event_id"]:
            event = gateway.get_event(dinner["calendar_event_id"])
            with store.transaction():
                apply(store, settings, dinner["id"], event)


def apply(store: Store, settings: Settings, dinner_id: int, event: Event) -> None:
    """Snapshot every on-calendar Guest's answer. A Guest moving between Declined and Attending is a Change."""
    answers = {attendee.email: attendee.response_status for attendee in event.attendees}
    moved = []
    for guest in store.guests(dinner_id):
        answer = answers.get(guest["email"])
        if not guest["on_calendar"] or answer is None or answer == guest["calendar_answer"]:
            continue  # off the calendar per Butler, or not there yet, or nothing new
        store.update_guest(dinner_id, guest["email"], calendar_answer=answer)
        was, now = status(guest), status(store.guest(dinner_id, guest["email"]))
        log.info("calendar: %s answered %s (%s → %s)", guest["email"], answer, was, now)
        if was != now:
            moved.append({"guest": guest["email"], "was": was, "now": now})
    if moved:
        change_id = store.add_change(dinner_id, "rsvp", {"via": "calendar", "moved": moved})
        effects.update_description(store, settings, dinner_id, change_id)
