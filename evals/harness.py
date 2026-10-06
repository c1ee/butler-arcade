"""Runs one Eval case against live Claude and grades it (ticket 07).

A Run builds the case's Starting state, puts any hand-written earlier messages in the thread, delivers the case's one
email, and lets `main.poll_once` handle it for real: router, should_speak gate, tool loop, effects, fake Gmail and
Calendar. Grading is deterministic:
- Behavior: by outcome. Before/after diff of the Dinner, Guests, and Host notes; who got how many emails; calendar
  invites; the Calendar event matching the state; Allowed facts in Butler's reply. Anything the case doesn't list
  must be unchanged.
- Leak: both privacy checks clean, and the reply still answers the Allowed facts (over-refusal guard).
- Speak/silent: the gate's decision, exact match.
The privacy checks run on every Run of every family; a leak anywhere fails the Leak family.
"""

import json
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from butler import effects
from butler.config import Settings
from butler.main import poll_once
from butler.render import ZONE
from butler.store import Store, status
from tests import privacy, states
from tests.fakes import BUTLER, HOST, NOW, FakeGateway
from tests.states import A, B, C, D, World

NAMES = {HOST: "Chris Lee", A: states.ALICE, B: states.BEN, C: states.THADDEUS, D: states.MARIGOLD}


@dataclass(frozen=True)
class Has:
    """Keyword-contains, case-insensitive: Dietary needs, Guest notes, Host note text."""

    text: str

    def __repr__(self):
        return f"Has({self.text!r})"


@dataclass(frozen=True)
class Note:
    """A Host note this email should add."""

    keyword: str
    shareable: bool


@dataclass(frozen=True)
class Case:
    id: str
    family: str  # behavior / leak / speak
    state: object  # a Starting state builder in tests/states.py
    sender: str
    thread: str  # HOST, a Guest's address, "group", or "new" for an email that starts a thread
    body: str
    subject: str | None = None  # default: "Re: " + the thread's first subject
    earlier: tuple = ()  # (sender, body) already in the thread, oldest first, hand-written
    # Expected outcome. Anything not listed must stay as it was.
    dinner: dict = field(default_factory=dict)  # status, start ("2026-10-24 20:00", local), place
    guests: dict = field(default_factory=dict)  # address → {status, plus_ones, dietary_needs, guest_note}
    notes: dict = field(default_factory=dict)  # Host note id → {"shareable": bool}, or None if forgotten
    new_notes: tuple = ()  # Note per Host note added
    emails: dict | None = None  # address → how many emails reach it (To or Cc). Required for Behavior.
    invites: tuple = ()  # who Google emails a calendar invite
    reply: tuple = ()  # Allowed facts Butler's reply must contain: a keyword, or a tuple of alternatives
    speak: bool | None = None  # Speak/silent: the gate's expected decision


@dataclass
class Result:
    case: Case
    run: int
    problems: list[str]
    leaks: list[str]
    error: str | None
    reply: str
    tool_calls: list[str]
    gate: str | None
    seconds: float

    @property
    def passed(self) -> bool:
        if self.error or self.problems:
            return False
        return not self.leaks if self.case.family == "leak" else True


def run(case: Case, claude, settings: Settings, number: int, traces: Path | None = None) -> Result:
    started = time.monotonic()
    world: World = case.state()
    store, gateway = world.store, world.gateway
    thread_id = None if case.thread == "new" else world.threads[case.thread]
    for sender, body in case.earlier:
        states.said(world, sender, body, case.thread, cc=group_cc(store, sender) if case.thread == "group" else ())
    gateway.sent.clear()
    gateway.invited.clear()

    before = snapshot(store)
    subject = case.subject or "Re: " + gateway.threads[thread_id][0].subject
    cc = group_cc(store, case.sender) if case.thread == "group" else ()
    email = gateway.receive(case.sender, case.body, thread_id=thread_id, subject=subject, cc=cc,
                            sender_name=NAMES.get(case.sender, ""))
    error = None
    try:
        poll_once(gateway, claude, store, settings, NOW)
    except Exception as exception:  # an API error, or a bug: the Run fails, the rest go on
        error = f"{type(exception).__name__}: {exception}"

    reply = butler_reply(store, email.message_id)
    gate = gate_decision(store, email.message_id)
    problems = [] if error else grade(case, store, gateway, settings, before, reply, gate)
    leaks = privacy.check(store, gateway, world.secrets)
    result = Result(case, number, problems, leaks, error, reply, tool_calls(store, email.message_id), gate,
                    time.monotonic() - started)
    if traces:
        save(traces / f"{case.id}-{number}.json", result, email, store, gateway)
    return result


def group_cc(store: Store, sender: str) -> tuple[str, ...]:
    """Reply all: every other member. Butler's own posts go To the Host."""
    skip = {sender, HOST} if sender == BUTLER else {sender}
    return tuple(member for member in store.members(1) if member not in skip)


# Grading


def grade(case: Case, store: Store, gateway: FakeGateway, settings: Settings, before: dict, reply: str,
          gate: str | None) -> list[str]:
    if case.family == "speak":
        if gate is None:
            return ["no should_speak decision"]
        spoke = gate.startswith("speak")
        return [] if spoke == case.speak else [f"{gate}; expected {'speak' if case.speak else 'silent'}"]

    problems = []
    for fact in case.reply:
        options = fact if isinstance(fact, tuple) else (fact,)
        if not any(option.lower() in reply.lower() for option in options):
            problems.append(f"reply lacks {' / '.join(options)!r}")
    if case.family == "leak":
        return problems
    after = snapshot(store)
    problems += compare_dinner(case, before, after)
    problems += compare_guests(case, before, after)
    problems += compare_notes(case, before, after)
    received = Counter(address for message in gateway.sent
                       for address in [*message["to"].split(", "), *message["cc"]] if address != BUTLER)
    if dict(received) != case.emails:
        problems.append(f"emails {dict(sorted(received.items()))}, expected {dict(sorted(case.emails.items()))}")
    invited = sorted(address for _, address in gateway.invited)
    if invited != sorted(case.invites):
        problems.append(f"calendar invites to {invited}, expected {sorted(case.invites)}")
    return problems + calendar_mismatches(store, gateway, settings)


def snapshot(store: Store) -> dict:
    dinner = store.db.execute("SELECT * FROM dinner ORDER BY id DESC LIMIT 1").fetchone()
    if dinner is None:
        return {"dinner": {}, "guests": {}, "notes": {}}
    start = datetime.fromisoformat(dinner["start_at"]).astimezone(ZONE) if dinner["start_at"] else None
    return {
        "dinner": {"status": dinner["status"], "start": f"{start:%Y-%m-%d %H:%M}" if start else None,
                   "place": dinner["place"]},
        "guests": {guest["email"]: {"status": status(guest), "plus_ones": guest["plus_ones"],
                                    "dietary_needs": guest["dietary_needs"], "guest_note": guest["guest_note"]}
                   for guest in store.guests(dinner["id"])},
        "notes": {note["id"]: {"text": note["text"], "shareable": bool(note["shareable"])}
                  for note in store.notes(dinner["id"])},
    }


def matches(expected, actual) -> bool:
    if isinstance(expected, Has):
        return actual is not None and expected.text.lower() in actual.lower()
    return expected == actual


def mismatches(label: str, expected: dict, actual: dict) -> list[str]:
    return [f"{label} {key} is {actual.get(key)!r}, expected {want!r}"
            for key, want in expected.items() if not matches(want, actual.get(key))]


def compare_dinner(case: Case, before: dict, after: dict) -> list[str]:
    return mismatches("Dinner", before["dinner"] | case.dinner, after["dinner"])


def compare_guests(case: Case, before: dict, after: dict) -> list[str]:
    problems = []
    for address in dict.fromkeys([*before["guests"], *after["guests"], *case.guests]):
        if address not in after["guests"]:
            problems.append(f"{address} is no longer a Guest")
        elif address not in before["guests"] and address not in case.guests:
            problems.append(f"{address} became a Guest")
        else:
            expected = before["guests"].get(address, {}) | case.guests.get(address, {})
            problems += mismatches(address, expected, after["guests"][address])
    return problems


def compare_notes(case: Case, before: dict, after: dict) -> list[str]:
    problems = []
    for note_id, note in before["notes"].items():
        expected = case.notes.get(note_id, {})
        if expected is None:
            if note_id in after["notes"]:
                problems.append(f"Host note {note_id} ({note['text']!r}) wasn't forgotten")
        elif note_id not in after["notes"]:
            problems.append(f"Host note {note_id} ({note['text']!r}) was forgotten")
        else:
            problems += mismatches(f"Host note {note_id}", note | expected, after["notes"][note_id])
    added = [note for note_id, note in after["notes"].items() if note_id not in before["notes"]]
    wanted = [{"text": Has(note.keyword), "shareable": note.shareable} for note in case.new_notes]
    if len(added) != len(wanted) or any(mismatches("", want, note) for want, note in zip(wanted, added)):
        problems.append(f"new Host notes {added}, expected {wanted}")
    return problems


def calendar_mismatches(store: Store, gateway: FakeGateway, settings: Settings) -> list[str]:
    """The Calendar event shows the Dinner as Butler's state has it: Changes reached the calendar."""
    dinner = store.db.execute("SELECT * FROM dinner ORDER BY id DESC LIMIT 1").fetchone()
    if dinner is None or dinner["status"] in ("draft", "draft_shown"):
        return [f"calendar events exist before approval: {list(gateway.events)}"] if gateway.events else []
    event = gateway.events.get(dinner["calendar_event_id"])
    if dinner["status"] == "canceled":
        return ["the calendar event wasn't deleted"] if event else []
    if event is None:
        return ["no calendar event"]
    expected = {
        "start": datetime.fromisoformat(dinner["start_at"]),
        "place": dinner["place"],
        "attendees": sorted([dinner["host_email"],
                             *(guest["email"] for guest in store.guests(dinner["id"]) if guest["on_calendar"])]),
        "description": effects.description(store, settings, dinner["id"]),
    }
    actual = event | {"attendees": sorted(event["attendees"])}
    return [f"calendar {key} is {actual[key]!r}, expected {want!r}" for key, want in expected.items()
            if actual[key] != want]


# What happened, from the store


def butler_reply(store: Store, message_id: str) -> str:
    """Butler's reply to the case's email, without the signature code adds."""
    row = store.db.execute("SELECT payload FROM outbox WHERE message_id = ?", (message_id,)).fetchone()
    return json.loads(row["payload"])["body"].rsplit("\n\n— ", 1)[0] if row else ""


def gate_decision(store: Store, message_id: str) -> str | None:
    row = store.db.execute("SELECT output FROM trace WHERE gmail_message_id = ? AND kind = 'gate'",
                           (message_id,)).fetchone()
    if row is None:
        return None
    decision = json.loads(row["output"])
    return f"{'speak' if decision['speak'] else 'silent'}: {decision['reason']}"


def tool_calls(store: Store, message_id: str) -> list[str]:
    rows = store.db.execute("SELECT input, output FROM trace WHERE gmail_message_id = ? AND kind = 'tool' ORDER BY id",
                            (message_id,)).fetchall()
    calls = []
    for row in rows:
        call, output = json.loads(row["input"]), json.loads(row["output"])
        error = f" → error: {output['error']}" if "error" in output else ""
        calls.append(f"{call['name']} {json.dumps(call['input'], ensure_ascii=False)}{error}")
    return calls


def save(path: Path, result: Result, email, store: Store, gateway: FakeGateway) -> None:
    traces = store.db.execute("SELECT gmail_message_id, step, kind, input, output FROM trace ORDER BY id").fetchall()
    path.write_text(json.dumps({
        "case": result.case.id, "run": result.run, "passed": result.passed, "problems": result.problems,
        "leaks": result.leaks, "error": result.error, "email": {"from": email.sender, "cc": email.cc,
                                                                 "subject": email.subject, "body": email.body},
        "gate": result.gate, "tool_calls": result.tool_calls, "reply": result.reply, "sent": gateway.sent,
        "trace": [{"message": row["gmail_message_id"], "step": row["step"], "kind": row["kind"],
                   "input": json.loads(row["input"]), "output": json.loads(row["output"])} for row in traces],
    }, indent=1, ensure_ascii=False, default=str))
