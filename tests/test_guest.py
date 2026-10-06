"""Guest flow (G1–G3, G6, G7): RSVPs by email, the calendar as the source of truth, answers from public facts."""

import json
from datetime import timedelta

import pytest

from butler import tools
from butler.main import poll_once, tick
from butler.store import Store, status
from butler.tools import Ctx, ToolError
from tests.fakes import HOST, NOW, SETTINGS, FakeGateway, ScriptedClaude, text, tool_use
from tests.states import A, B, approved, event, on_calendar


@pytest.fixture
def setup():
    world = approved()
    return world.store, world.gateway, world.threads


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
    assert "Coming: 2 (August + 1 more)" in event(store, gateway)["description"]

    notice, reply = gateway.sent
    assert (notice["to"], notice["thread_id"]) == (HOST, store.dinner(1)["host_thread_id"])
    assert "August Lee (a@example.com) is coming!" in notice["body"] and "vegetarian" in notice["body"]
    assert "Headcount is now 2." in notice["body"]
    assert (reply["to"], reply["thread_id"]) == (A, threads[A])
    assert "street parking only" in reply["body"] and reply["body"].endswith("— Butler, on behalf of Chris")

    request = claude.requests[0]
    assert [tool["name"] for tool in request["tools"]] == ["get_event", "get_my_rsvp", "record_rsvp"]
    assert "Street parking only" in request["messages"][0]["content"]


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


def test_a_plus_n_on_the_calendar_is_ignored(setup):
    store, gateway, _ = setup
    on_calendar(store, gateway, A, "needsAction")
    event(store, gateway)["answers"][A] = "accepted"
    event(store, gateway)["extra"][A] = 2  # "+2" in Google's RSVP: Plus-ones are email only (D13)
    tick(gateway, store, SETTINGS, NOW)
    assert store.guest(1, A)["plus_ones"] == 0 and tools.public_facts(store, 1)["headcount"] == 1
    assert gateway.sent == []


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


def test_a_guests_own_details_stay_out_of_the_public_facts(ctx):
    call(ctx, "record_rsvp", attending=True, dietary_needs="vegetarian")
    public = json.dumps(call(ctx, "get_event"))
    assert "Street parking only" in public and A in public and "vegetarian" not in public
    assert "vegetarian" in json.dumps(call(ctx, "get_my_rsvp"))
