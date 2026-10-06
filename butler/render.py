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


def guest_label(guest) -> str:
    """How others see a Guest: display name from their emails, else their address."""
    return guest["name"] or guest["email"]


def coming(names: list[str], headcount: int) -> str:
    """Coming: 3 (August Lee, Xhaka + 1 more). Per-Guest Plus-ones stay private (own scope), only the total shows."""
    if not names:
        return "Coming: no guests yet"
    extra = headcount - len(names)
    return f"Coming: {headcount} ({', '.join(names)}{f' + {extra} more' if extra else ''})"


def _and(names: list[str]) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def _facts(dinner, coming_names: list[str], headcount: int) -> list[str]:
    return [f"When: {when(_start(dinner))}", f"Where: {dinner['place']}", coming(coming_names, headcount)]


def group_opener(dinner, coming_names: list[str], headcount: int) -> tuple[str, str]:
    """(subject, body) of the email that starts the Group thread once enough Guests say yes (H3)."""
    host = host_label(dinner)
    lines = [
        "Hi all,",
        "",
        f"Enough of you said yes, so here's one thread for {host} and everyone coming. Reply all to reach everyone.",
        "",
        *_facts(dinner, coming_names, headcount),
        "",
        'I\'ll stay quiet here unless you ask me something ("Butler, ..."). To change your RSVP, reply here or to '
        "my invite.",
    ]
    return f"Group thread: {title(dinner)}, {short_when(_start(dinner))}", sign("\n".join(lines), dinner)


def welcome(dinner, joiner_names: list[str], coming_names: list[str], headcount: int) -> str:
    """The Group thread post that adds Guests who said yes after it started (H3). Current facts, no catch-up."""
    lines = [f"Welcome, {_and(joiner_names)}! You're on the group thread now.", "",
             *_facts(dinner, coming_names, headcount)]
    return sign("\n".join(lines), dinner)


def host_notice(guest, was: str, now: str, headcount: int) -> str:
    """The Host's private notice after a Guest's RSVP changes by email (G1–G3). Calendar answers don't get one (D13)."""
    who = f"{guest['name']} ({guest['email']})" if guest["name"] else guest["email"]
    if now == "attending" and was != "attending":
        lines = [f"{who} is coming!"]
    elif now == "declined" and was != "declined":
        lines = [f"{who} can't make it."]
    else:
        lines = [f"{who} updated their RSVP."]
    if now == "attending":
        lines.append(f"Bringing: {guest['plus_ones'] or 'no one'} {'more' if guest['plus_ones'] else ''}".rstrip())
        if guest["dietary_needs"]:
            lines.append(f"Dietary needs: {guest['dietary_needs']}")
        if guest["guest_note"]:
            lines.append(f"Note: {guest['guest_note']}")
    lines += ["", f"Headcount is now {headcount}."]
    return sign("\n".join(lines))


def description(dinner, notes, coming_names: list[str], headcount: int, butler_email: str) -> str:
    """The Calendar event description: public scope only (D3), re-rendered on every Change."""
    host = host_label(dinner)
    lines = [
        f"Hosted by {host}. Organized by Butler ({butler_email}): to change your RSVP or ask a question, "
        "reply to Butler's email.",
        "",
        coming(coming_names, headcount),
    ]
    if shared := _shareable(notes):
        lines += ["", f"From {host}:", *shared]
    return "\n".join(lines)
