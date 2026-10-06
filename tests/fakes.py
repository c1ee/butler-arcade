"""Stand-ins for Arcade (FakeGateway) and Claude (ScriptedClaude) in deterministic tests."""

from datetime import UTC, datetime
from itertools import count
from types import SimpleNamespace

from butler.config import Settings
from butler.gateway import Email, Sent

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
                                 "description": description, "attendees": [host]}
        return event_id


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
