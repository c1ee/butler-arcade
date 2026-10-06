"""Guest flow (G1–G3, G6, G7): RSVPs by email, the calendar as the source of truth, answers from public facts."""

import json
from datetime import timedelta

import pytest

from butler import tools
from butler.main import poll_once, tick
from butler.router import Route
from butler.store import Store, status
from butler.tools import Ctx, ToolError
from tests.fakes import HOST, NOW, SETTINGS, FakeGateway, ScriptedClaude, text, tool_use

A, B, C = "a@example.com", "b@example.com", "c@example.com"
SECRETS = ["zeppelin", "quince", "oboe", B, C]  # private Host note, C's Dietary needs, B's Guest note, Invited/Declined


def approved(store: Store, gateway: FakeGateway) -> dict[str, str]:
    """Starting state: an approved Dinner. A and B Invited (B has a Guest note), C Declined by email with Dietary
    needs, one shareable and one private Host note, Host only on the calendar. Returns each Guest's thread id."""
    first = gateway.receive(HOST, "dinner sat 10/24 7pm at 12 Elm St", sender_name="Chris Lee")
    event_id = gateway.create_event("Dinner with Chris", None, None, "12 Elm St", "", HOST)
    threads = {}
    with store.transaction():
        store.create_dinner(status="active", title="Dinner with Chris", host_email=HOST, host_name="Chris Lee",
                            start_at="2026-10-24T19:00:00-07:00", place="12 Elm St", host_thread_id=first.thread_id,
                            calendar_event_id=event_id)
        store.mark_processed(first, Route(1, "host_thread", "host"), NOW)
        store.add_note(1, "Street parking only", True)
        store.add_note(1, "Bob's surprise is a zeppelin ride", False)
        for guest in (A, B, C):
            threads[guest] = gateway.send(guest, "You're invited: Dinner with Chris", "Can you make it?").thread_id
            store.add_guest(1, guest, guest_thread_id=threads[guest])
        store.update_guest(1, B, guest_note="leaving early for an oboe recital")
        store.update_guest(1, C, email_answer="no", dietary_needs="allergic to quince")
    gateway.sent.clear()
    gateway.invited.clear()
    return threads


def on_calendar(store: Store, gateway: FakeGateway, guest: str, answer: str) -> None:
    """Put a Guest on the calendar with an answer, as if they'd said yes earlier and then clicked `answer`."""
    event_id = store.dinner(1)["calendar_event_id"]
    gateway.add_attendee(event_id, guest)
    gateway.events[event_id]["answers"][guest] = answer
    gateway.invited.clear()
    with store.transaction():
        store.update_guest(1, guest, email_answer="yes", on_calendar=1, calendar_answer=answer)


def event(store: Store, gateway: FakeGateway) -> dict:
    return gateway.events[store.dinner(1)["calendar_event_id"]]


def assert_no_secrets(claude: ScriptedClaude, gateway: FakeGateway, allowed=()):
    """Input check (everything Claude saw) and output check (everything sent, the calendar event) for a Guest."""
    seen = json.dumps([claude.requests, gateway.sent, list(gateway.events.values())], default=str)
    leaked = [secret for secret in SECRETS if secret not in allowed and secret in seen]
    assert not leaked


@pytest.fixture
def setup():
    store, gateway = Store(":memory:"), FakeGateway()
    return store, gateway, approved(store, gateway)


def test_yes_with_question_adds_the_attendee_and_answers_from_a_shareable_note(setup):
    store, gateway, threads = setup
    claude = ScriptedClaude(
        [tool_use("record_rsvp", attending=True, plus_ones=1, dietary_needs="vegetarian")],
        [text("You're in, see you Saturday! Parking: street parking only.")],
    )
    gateway.receive(A, "yes! bringing my partner, she's vegetarian. what's parking like?", thread_id=threads[A],
                    sender_name="August Lee")
    poll_once(gateway, claude, store, SETTINGS, NOW)

    guest = store.guest(1, A)
    assert (status(guest), guest["plus_ones"], guest["dietary_needs"]) == ("attending", 1, "vegetarian")
    assert event(store, gateway)["attendees"] == [HOST, A]
    assert gateway.invited == [(store.dinner(1)["calendar_event_id"], A)]  # Google emails A only
    assert "Coming: 2 (August Lee + 1 more)" in event(store, gateway)["description"]

    notice, reply = gateway.sent
    assert (notice["to"], notice["thread_id"]) == (HOST, store.dinner(1)["host_thread_id"])
    assert "August Lee (a@example.com) is coming!" in notice["body"] and "vegetarian" in notice["body"]
    assert "Headcount is now 2." in notice["body"]
    assert (reply["to"], reply["thread_id"]) == (A, threads[A])
    assert "street parking only" in reply["body"] and reply["body"].endswith("— Butler, on behalf of Chris")

    request = claude.requests[0]
    assert [tool["name"] for tool in request["tools"]] == ["get_event", "get_my_rsvp", "record_rsvp"]
    assert "Street parking only" in request["messages"][0]["content"]
    assert_no_secrets(claude, gateway)


def test_a_question_alone_changes_nothing(setup):
    store, gateway, threads = setup
    claude = ScriptedClaude([text("I don't know, best to ask Chris directly.")])
    gateway.receive(A, "is there a dress code?", thread_id=threads[A])
    poll_once(gateway, claude, store, SETTINGS, NOW)
    assert status(store.guest(1, A)) == "invited"
    assert [m["to"] for m in gateway.sent] == [A] and gateway.invited == []
    assert store.db.execute("SELECT COUNT(*) FROM change").fetchone()[0] == 0


def test_yes_then_no_in_one_email_leaves_the_calendar_alone_and_tells_the_host_once(setup):
    store, gateway, threads = setup
    claude = ScriptedClaude(
        [tool_use("record_rsvp", attending=True)], [tool_use("record_rsvp", attending=False)],
        [text("No worries, thanks for letting me know!")],
    )
    gateway.receive(A, "yes! wait no, I have a thing. sorry", thread_id=threads[A])
    poll_once(gateway, claude, store, SETTINGS, NOW)
    assert status(store.guest(1, A)) == "declined"
    assert gateway.invited == [] and event(store, gateway)["attendees"] == [HOST]
    notices = [m for m in gateway.sent if m["to"] == HOST]
    assert len(notices) == 1 and "a@example.com can't make it." in notices[0]["body"]
    assert event(store, gateway)["description"] == ""  # Headcount didn't move: no calendar write


def test_no_after_yes_takes_them_off_the_calendar_silently(setup):
    store, gateway, threads = setup
    on_calendar(store, gateway, A, "accepted")
    claude = ScriptedClaude([tool_use("record_rsvp", attending=False)], [text("Sorry to miss you, thanks!")])
    gateway.receive(A, "so sorry, something came up", thread_id=threads[A])
    poll_once(gateway, claude, store, SETTINGS, NOW)
    assert status(store.guest(1, A)) == "declined" and not store.guest(1, A)["on_calendar"]
    assert event(store, gateway)["attendees"] == [HOST] and gateway.invited == []
    assert "Coming: no guests yet" in event(store, gateway)["description"]
    assert [m["to"] for m in gateway.sent] == [HOST, A]


def test_yes_by_email_after_a_calendar_no_re_adds_them_once(setup):
    store, gateway, threads = setup
    on_calendar(store, gateway, A, "declined")
    claude = ScriptedClaude([tool_use("record_rsvp", attending=True)], [text("Great, you're back in!")])
    gateway.receive(A, "changed my mind, I'm in!", thread_id=threads[A])
    poll_once(gateway, claude, store, SETTINGS, NOW)
    assert status(store.guest(1, A)) == "attending"
    event_id = store.dinner(1)["calendar_event_id"]
    assert gateway.invited == [(event_id, A)]  # one fresh invite
    assert gateway.get_event(event_id).attendees[1].response_status == "needsAction"
    tick(gateway, store, SETTINGS, NOW)
    assert store.guest(1, A)["calendar_answer"] == "needsAction"  # sync agrees: nothing moved


def test_a_guest_email_before_approval_is_not_answered():
    store, gateway = Store(":memory:"), FakeGateway()
    with store.transaction():
        store.create_dinner(host_email=HOST, host_thread_id="t0")
        store.add_guest(1, A)
    gateway.receive(A, "yes!")
    poll_once(gateway, ScriptedClaude(), store, SETTINGS, NOW)  # no script: Claude must not be called
    assert gateway.sent == [] and store.is_processed("m1")


# The calendar decides who's coming (G7, D13)


def test_calendar_answers_move_headcount_silently(setup):
    store, gateway, _ = setup
    store.update_dinner(1, group_threshold=5)  # no Group thread here: tests/test_group.py
    on_calendar(store, gateway, A, "needsAction")
    on_calendar(store, gateway, B, "needsAction")
    answers = event(store, gateway)["answers"]

    answers[B] = "declined"
    tick(gateway, store, SETTINGS, NOW)
    assert status(store.guest(1, B)) == "declined" and B in event(store, gateway)["attendees"]
    assert "Coming: 1 (a@example.com)" in event(store, gateway)["description"]

    answers[B] = "tentative"  # Maybe counts as coming
    tick(gateway, store, SETTINGS, NOW + timedelta(seconds=30))
    assert status(store.guest(1, B)) == "attending"
    assert "Coming: 2" in event(store, gateway)["description"]

    answers[A] = "accepted"  # still coming: snapshot only
    event(store, gateway)["description"] = "untouched"
    tick(gateway, store, SETTINGS, NOW + timedelta(seconds=60))
    assert store.guest(1, A)["calendar_answer"] == "accepted"
    assert event(store, gateway)["description"] == "untouched"
    assert gateway.sent == [] and gateway.invited == []  # nobody is emailed about calendar answers


def test_sync_waits_for_queued_calendar_writes(setup):
    store, gateway, _ = setup
    with store.transaction():
        store.queue("calendar", A, {"kind": "add_attendee", "dinner_id": 1}, change_id=store.add_change(1, "rsvp"))
    gateway.get_event = lambda event_id: pytest.fail("read the calendar with a write still queued")
    gateway.add_attendee = lambda event_id, email: (_ for _ in ()).throw(RuntimeError("Arcade down"))
    tick(gateway, store, SETTINGS, NOW)


def test_sync_ignores_attendees_butler_took_off(setup):
    store, gateway, _ = setup
    event(store, gateway)["attendees"].append(A)  # removal not applied yet, or someone added A by hand
    event(store, gateway)["answers"][A] = "accepted"
    tick(gateway, store, SETTINGS, NOW)
    assert status(store.guest(1, A)) == "invited"


# Tools


@pytest.fixture
def ctx(setup):
    store, _, _ = setup
    return Ctx(store, SETTINGS, 1, A, NOW)


def call(ctx, name, **args):
    return tools.TOOLS[name].call(ctx, args)


def test_record_rsvp_writes_only_for_the_sender(ctx):
    before = dict(ctx.store.guest(1, B))
    result = call(ctx, "record_rsvp", attending=True, plus_ones=2, note_for_host="arriving late")
    assert result["recorded"] == {"status": "attending", "plus_ones": 2, "dietary_needs": None,
                                  "note_for_host": "arriving late"}
    assert "calendar invite" in result["calendar"]
    assert dict(ctx.store.guest(1, B)) == before


def test_record_rsvp_keeps_details_unless_given_and_clears_on_empty(ctx):
    call(ctx, "record_rsvp", attending=True, plus_ones=1, dietary_needs="vegan")
    call(ctx, "record_rsvp", attending=True)
    assert (ctx.store.guest(1, A)["plus_ones"], ctx.store.guest(1, A)["dietary_needs"]) == (1, "vegan")
    call(ctx, "record_rsvp", attending=True, dietary_needs=" ")
    assert ctx.store.guest(1, A)["dietary_needs"] is None


def test_record_rsvp_refuses_once_the_dinner_is_not_live(ctx):
    ctx.store.update_dinner(1, status="canceled")
    with pytest.raises(ToolError, match="isn't taking RSVPs"):
        call(ctx, "record_rsvp", attending=True)


def test_guest_reads_carry_no_secrets(ctx):
    call(ctx, "record_rsvp", attending=True, dietary_needs="vegetarian")
    public = json.dumps(call(ctx, "get_event"))
    assert "Street parking only" in public and A in public
    assert not [secret for secret in SECRETS + ["vegetarian"] if secret in public]
    own = json.dumps(call(ctx, "get_my_rsvp"))
    assert "vegetarian" in own and not [secret for secret in SECRETS if secret in own]
