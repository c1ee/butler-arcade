"""Email → (Dinner, channel, role). Decided from thread id and sender address, never from the body."""

import re
from dataclasses import dataclass

from butler.config import Settings
from butler.gateway import Email
from butler.store import OVER, Store

# Google's and Outlook's automatic RSVP emails ("Accepted: Dinner @ Sat …"), each a new thread
# from the Guest's address. Not conversation: the per-poll calendar read picks up the answer (D13).
CALENDAR_REPLY = re.compile(r"^(Accepted|Declined|Tentatively accepted|Tentative):\s", re.IGNORECASE)


@dataclass(frozen=True)
class Route:
    dinner_id: int | None  # None with the Host thread channel: a new Dinner starts here
    channel: str | None  # host_thread / guest_thread / group_thread
    role: str  # host / guest / stranger / butler
    skipped: str | None = None  # why Butler won't act on it


def readers(email: Email, butler_email: str) -> set[str]:
    """Everyone an email reached, its sender included, Butler left out."""
    return {email.sender, *email.to, *email.cc} - {butler_email}


def private(email: Email, butler_email: str) -> bool:
    """Between one person and Butler, whoever sent it. In the Group thread, a plain Reply to Butler and Butler's
    answer to it are private, not posts to the group."""
    return len(readers(email, butler_email)) < 2


def route(email: Email, store: Store, settings: Settings) -> Route:
    sender = email.sender
    if sender == settings.butler_email:
        return Route(None, None, "butler", skipped="Butler's own email")

    known = store.find_thread(email.thread_id)
    dinner = known[0] if known else store.current_dinner()
    dinner_id = dinner["id"] if dinner else None

    if sender == settings.host_email:
        role = "host"
    elif dinner and store.guest(dinner_id, sender):
        role = "guest"
    else:
        role = "stranger"

    if CALENDAR_REPLY.match(email.subject):
        return Route(dinner_id, None, role, skipped="calendar reply")
    if role == "stranger":
        return Route(dinner_id, None, role, skipped="unknown sender")
    if dinner and dinner["status"] in OVER:
        return Route(dinner_id, None, role, skipped=f"Dinner {dinner['status']}")

    if known:
        _, channel, thread_guest = known
        if channel == "host_thread" and role != "host":
            return Route(dinner_id, channel, role, skipped="not the Host")
        if channel == "guest_thread" and sender != thread_guest:
            return Route(dinner_id, channel, role, skipped="not this Guest's thread")
        if channel == "group_thread" and private(email, settings.butler_email):
            # Sent only to Butler (a plain Reply does that), so Butler answers the sender alone.
            channel = "host_thread" if role == "host" else "guest_thread"
        return Route(dinner_id, channel, role)

    # A new thread: an email written fresh, or a reply to Google's calendar invite. Route by sender.
    return Route(dinner_id, "host_thread" if role == "host" else "guest_thread", role)
