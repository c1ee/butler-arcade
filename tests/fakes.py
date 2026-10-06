"""Stand-ins for Arcade (FakeGateway) and Claude (ScriptedClaude) in deterministic tests."""

from datetime import UTC, datetime
from itertools import count
from types import SimpleNamespace

from butler.config import Settings
from butler.gateway import Attendee, Email, Event, Sent

BUTLER = "butler@example.com"
HOST = "host@example.com"
SETTINGS = Settings(arcade_api_key="", anthropic_api_key="", butler_user_id=BUTLER, host_email=HOST, model="test")
NOW = datetime(2026, 10, 6, 20, 0, tzinfo=UTC)  # Tuesday 1 PM in Los Angeles


def gmail_quote(email: Email) -> str:
    """What Gmail pastes below a reply (ticket 05): an attribution line, then the replied-to email, quote and all."""
    who = f"{email.sender_name} <{email.sender}>" if email.sender_name else email.sender
    quoted = "\n".join(f"> {line}" if line else ">" for line in email.body.splitlines())
    return f"\n\nOn Tue, Oct 6, 2026 at 1:00 PM {who} wrote:\n\n{quoted}"


class FakeGateway:
    """Butler's mailbox and calendar in memory. Replies go to the replied-to email's sender, in its thread, and quote
    it like Gmail."""

    def __init__(self):
        self.inbox: list[Email] = []
        self.threads: dict[str, list[Email]] = {}
        self.sent: list[dict] = []
        self.events: dict[str, dict] = {}
        self.invited: list[tuple[str, str]] = []  # (event id, email) for every calendar invite Google sent
        self._ids = count(1)

    def receive(self, sender, body, thread_id=None, subject="dinner", sender_name="", cc=()) -> Email:
        n = next(self._ids)
        email = Email(f"m{n}", thread_id or f"t{n}", sender, (BUTLER,), tuple(cc), subject, body, NOW, sender_name)
        self.inbox.append(email)
        self.threads.setdefault(email.thread_id, []).append(email)
        return email

    def add_to_thread(self, sender, body, thread_id, to=(BUTLER,), cc=(), sender_name="") -> Email:
        """An email already in a thread before the test starts: in the thread, not new in the inbox."""
        email = Email(f"m{next(self._ids)}", thread_id, sender, tuple(to), tuple(cc), "dinner", body, NOW, sender_name)
        self.threads.setdefault(thread_id, []).append(email)
        return email

    def search_inbox(self, after):
        return list(self.inbox)

    def get_thread(self, thread_id):
        return list(self.threads.get(thread_id, []))

    def _deliver(self, thread_id, to: list, cc: list, subject, body, quote="") -> Sent:
        """`body` is what Butler wrote; `quote` what Gmail pasted below it. Recipients read both."""
        message_id = f"m{next(self._ids)}"
        self.sent.append({"to": ", ".join(to), "cc": cc, "subject": subject, "body": body, "quote": quote,
                          "thread_id": thread_id})
        email = Email(message_id, thread_id, BUTLER, tuple(to), tuple(cc), subject, body + quote, NOW, "Butler")
        self.threads.setdefault(thread_id, []).append(email)
        return Sent(message_id, thread_id)

    def send(self, to, subject, body, cc=None):
        return self._deliver(f"t{next(self._ids)}", [to], list(cc or []), subject, body)

    def reply(self, message_id, body, cc=None, to_sender_only=True):
        """Like Gmail (tickets 05, 12): to the replied-to email's sender, Butler itself if it's Butler's own; or for
        every_recipient, its sender and To minus Butler, with its Cc merged in. Cc drops Butler and anyone in To."""
        original = next(e for thread in self.threads.values() for e in thread if e.message_id == message_id)
        if to_sender_only:
            to, merged = [original.sender], list(cc or [])
        else:
            to = [a for a in dict.fromkeys((original.sender, *original.to)) if a != BUTLER]
            merged = [*original.cc, *(cc or [])]
        cc = [address for address in dict.fromkeys(merged) if address != BUTLER and address not in to]
        return self._deliver(original.thread_id, to, cc, "Re: " + original.subject, body, gmail_quote(original))

    def create_event(self, title, start, end, place, description, host):
        event_id = f"e{next(self._ids)}"
        self.events[event_id] = {"title": title, "start": start, "end": end, "place": place,
                                 "description": description, "attendees": [host], "answers": {}, "extra": {}}
        self.invited.append((event_id, host))
        return event_id

    # Like Google: only creating the event and adding an attendee email anyone (`invited`); a removed attendee's
    # answer is forgotten, so a re-added one is awaiting again. `extra` holds a Guest's "+N" from the invite.

    def get_event(self, event_id):
        event = self.events[event_id]
        attendees = tuple(Attendee(email, event["answers"].get(email, "needsAction"), event["extra"].get(email, 0))
                          for email in event["attendees"])
        return Event(event_id, event["title"], event["start"], event["end"], event["place"], event["description"],
                     attendees)

    def update_event(self, event_id, start=None, end=None, place=None, description=None):
        changes = {"start": start, "end": end, "place": place, "description": description}
        self.events[event_id] |= {key: value for key, value in changes.items() if value is not None}

    def add_attendee(self, event_id, email):
        if email not in self.events[event_id]["attendees"]:
            self.events[event_id]["attendees"].append(email)
        self.invited.append((event_id, email))

    def delete_event(self, event_id):
        """Silently, like `send_updates="nobody"`: nobody is emailed."""
        del self.events[event_id]

    def remove_attendee(self, event_id, email):
        event = self.events[event_id]
        event["attendees"] = [attendee for attendee in event["attendees"] if attendee != email]
        event["answers"].pop(email, None)


def text(value):
    return SimpleNamespace(type="text", text=value)


def tool_use(name, **input):
    return SimpleNamespace(type="tool_use", id=f"use-{name}", name=name, input=input)


class ScriptedClaude:
    """Returns the scripted responses in order, each a list of blocks, and records every request."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.messages = self

    def create(self, **request):
        self.requests.append(request)
        content = self.responses.pop(0)
        stop = "tool_use" if any(block.type == "tool_use" for block in content) else "end_turn"
        return SimpleNamespace(content=content, stop_reason=stop)
