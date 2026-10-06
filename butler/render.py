"""Every system email and the Calendar description, as templates (D8). Claude never writes these."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from butler.config import TIMEZONE

ZONE = ZoneInfo(TIMEZONE)
EVENT_LENGTH = timedelta(hours=3)  # the calendar block; Butler stops at start + 1h (store.close_finished)
RULE = "-" * 30


def clock(at: datetime) -> str:
    local = at.astimezone(ZONE)
    minutes = f":{local:%M}" if local.minute else ""
    return f"{local.hour % 12 or 12}{minutes} {local:%p}"


def when(at: datetime) -> str:
    """Saturday, October 24 at 7 PM"""
    local = at.astimezone(ZONE)
    return f"{local:%A, %B} {local.day} at {clock(local)}"


def short_when(at: datetime) -> str:
    """Sat Oct 24, 7 PM"""
    local = at.astimezone(ZONE)
    return f"{local:%a %b} {local.day}, {clock(local)}"


def host_label(dinner) -> str:
    """How Guests see the Host: first name if their email had one, else their address."""
    name = (dinner["host_name"] or "").split()
    return name[0] if name else dinner["host_email"]


def title(dinner) -> str:
    name = (dinner["host_name"] or "").split()
    return f"Dinner with {name[0]}" if name else "Dinner"


def sign(body: str, dinner=None) -> str:
    """Butler's signature: plain to the Host, on the Host's behalf to anyone else."""
    signature = f"Butler, on behalf of {host_label(dinner)}" if dinner else "Butler"
    return f"{body.rstrip()}\n\n— {signature}"


def _start(dinner) -> datetime:
    return datetime.fromisoformat(dinner["start_at"])


def _shareable(notes) -> list[str]:
    return [f"- {note['text']}" for note in notes if note["shareable"]]


def invite(dinner, notes) -> tuple[str, str]:
    """(subject, body) of the private invite each Guest gets (H2). Never names other Guests."""
    host = host_label(dinner)
    lines = [
        "Hi,",
        "",
        f"I'm Butler, helping {host} organize a dinner, and you're invited!",
        "",
        f"When: {when(_start(dinner))}",
        f"Where: {dinner['place']}",
    ]
    if shared := _shareable(notes):
        lines += ["", f"From {host}:", *shared]
    lines += [
        "",
        "Can you make it? Just reply to this email with yes or no.",
        f"Bring whoever you like, just tell me how many and I'll let {host} know. "
        f"Any dietary needs? Mention them too; only {host} will see them.",
        "",
        "To change your RSVP or ask a question later, just reply to this email.",
    ]
    return f"You're invited: {title(dinner)}, {short_when(_start(dinner))}", sign("\n".join(lines), dinner)


def draft_preview(dinner, notes, guests) -> str:
    """The complete draft, shown to the Host below Butler's reply before anything is sent (H1, D9)."""
    start = _start(dinner)
    subject, body = invite(dinner, notes)
    lines = [
        "Here's the draft:",
        "",
        f"When: {when(start)} (on the calendar until {clock(start + EVENT_LENGTH)})",
        f"Where: {dinner['place']}",
        f"Guests: {', '.join(guest['email'] for guest in guests)}",
    ]
    if notes:
        lines.append("Your notes:")
        lines += [
            f"- {note['text']} ({'shareable: in the invite and on the calendar' if note['shareable'] else 'private: only you see it'})"
            for note in notes
        ]
    threshold = dinner["group_threshold"]
    lines += [
        f"Group thread: I'll start one with you and everyone coming once {threshold} "
        f"guest{'s say' if threshold != 1 else ' says'} yes.",
        "",
        "Each guest gets this invite on their own, so nobody sees who else is invited:",
        "",
        RULE,
        f"Subject: {subject}",
        "",
        body,
        RULE,
        "",
        'Reply "send it" and I\'ll send the invites and put the dinner on your calendar. Or tell me what to change.',
    ]
    return "\n".join(lines)


def description(dinner, notes, coming: list[str], headcount: int, butler_email: str) -> str:
    """The Calendar event description: public scope only (D3), re-rendered on every Change."""
    host = host_label(dinner)
    lines = [
        f"Hosted by {host}. Organized by Butler ({butler_email}): to change your RSVP or ask a question, "
        "reply to Butler's email.",
        "",
        f"Coming: {headcount} ({', '.join(coming)})" if coming else "Coming: no guests yet",
    ]
    if shared := _shareable(notes):
        lines += ["", f"From {host}:", *shared]
    return "\n".join(lines)
