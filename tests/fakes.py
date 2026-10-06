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


class FakeGateway:
    """Butler's mailbox and calendar in memory. Replies go to the replied-to email's sender, in its thread."""

    def __init__(self):
        self.inbox: list[Email] = []
        self.threads: dict[str, list[Email]] = {}
        self.sent: list[dict] = []
        self.events: dict[str, dict] = {}
        self.invited: list[tuple[str, str]] = []  # (event id, email) for every calendar invite Google sent
        self._ids = count(1)

    def receive(self, sender, body, thread_id=None, subject="dinner", sender_name="") -> Email:
        n = next(self._ids)
        email = Email(f"m{n}", thread_id or f"t{n}", sender, (BUTLER,), (), subject, body, NOW, sender_name)
        self.inbox.append(email)
        self.threads.setdefault(email.thread_id, []).append(email)
        return email

    def search_inbox(self, after):
        return list(self.inbox)

    def get_thread(self, thread_id):
        return list(self.threads.get(thread_id, []))

    def _deliver(self, thread_id, to, cc, subject, body) -> Sent:
        message_id = f"m{next(self._ids)}"
        self.sent.append({"to": to, "cc": cc, "subject": subject, "body": body, "thread_id": thread_id})
        email = Email(message_id, thread_id, BUTLER, (to,), tuple(cc), subject, body, NOW, "Butler")
        self.threads.setdefault(thread_id, []).append(email)
        return Sent(message_id, thread_id)

    def send(self, to, subject, body, cc=None):
        return self._deliver(f"t{next(self._ids)}", to, cc or [], subject, body)

    def reply(self, message_id, body, cc=None, to_sender_only=True):
        original = next(e for thread in self.threads.values() for e in thread if e.message_id == message_id)
        return self._deliver(original.thread_id, original.sender, cc or [], "Re: " + original.subject, body)

    def create_event(self, title, start, end, place, description, host):
        event_id = f"e{next(self._ids)}"
        self.events[event_id] = {"title": title, "start": start, "end": end, "place": place,
                                 "description": description, "attendees": [host], "answers": {}}
        self.invited.append((event_id, host))
        return event_id

    # Like Google: only creating the event and adding an attendee email anyone (`invited`); a removed attendee's
    # answer is forgotten, so a re-added one is awaiting again.

    def get_event(self, event_id):
        event = self.events[event_id]
        attendees = tuple(Attendee(email, event["answers"].get(email, "needsAction"), 0) for email in event["attendees"])
        return Event(event_id, event["title"], event["start"], event["end"], event["place"], event["description"],
                     attendees)

    def update_event(self, event_id, start=None, end=None, place=None, description=None):
        changes = {"start": start, "end": end, "place": place, "description": description}
        self.events[event_id] |= {key: value for key, value in changes.items() if value is not None}

    def add_attendee(self, event_id, email):
        if email not in self.events[event_id]["attendees"]:
            self.events[event_id]["attendees"].append(email)
        self.invited.append((event_id, email))

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
