"""The Host after approval (H4, H5, H6, H8): Changes reach the calendar, the Group thread, and every Invited or
Attending Guest outside it exactly once; notes flip silently; cancel only after Butler asked to confirm."""

from datetime import datetime, timedelta

import pytest

from butler import tools
from butler.main import poll_once, tick
from butler.render import ZONE
from butler.store import status
from butler.tools import Ctx, ToolError
from tests import states
from tests.fakes import HOST, NOW, SETTINGS, ScriptedClaude, text, tool_use
from tests.states import A, B, C, D, event
from tests.test_group import decide


@pytest.fixture
def live():
    """A and B Attending and in the Group thread, C Declined by email, D Invited. Returns (store, gateway, threads)."""
    world = states.live()
    return world.store, world.gateway, world.threads


def host_says(store, gateway, threads, claude, body, channel=HOST, cc=()):
    gateway.receive(HOST, body, thread_id=threads[channel], cc=cc)
    poll_once(gateway, claude, store, SETTINGS, NOW)


def to(gateway, address):
    return [m for m in gateway.sent if m["to"] == address]


def test_a_time_change_reaches_every_channel_once(live):
    store, gateway, threads = live
    claude = ScriptedClaude([tool_use("change_event", start="2026-10-24T20:00")], [text("Done: it's at 8 now.")])
    host_says(store, gateway, threads, claude, "push it back an hour")

    assert store.dinner(1)["start_at"] == "2026-10-24T20:00:00-07:00"
    calendar = event(store, gateway)
    assert (calendar["start"].astimezone(ZONE).hour, calendar["end"] - calendar["start"]) == (20, timedelta(hours=3))
    assert gateway.invited == []  # Google emails nobody

    group, d, reply = gateway.sent
    assert (group["to"], group["cc"], group["thread_id"]) == (HOST, [A, B], threads["group"])
    assert group["body"].startswith("Hi all,") and "When: Saturday, October 24 at 8 PM (was 7 PM)" in group["body"]
    assert (d["to"], d["cc"], d["thread_id"]) == (D, [], threads[D])
    assert "(was 7 PM)" in d["body"] and "Can you make it?" in d["body"]
    assert (reply["to"], reply["thread_id"]) == (HOST, threads[HOST])
    assert to(gateway, C) == []  # Declined outside the group: nothing

    request = claude.requests[0]
    assert "cancel_dinner" not in [t["name"] for t in request["tools"]]
    assert "oboe" in request["messages"][0]["content"]  # the Host thread sees every Guest's details

    sent = len(gateway.sent)
    poll_once(gateway, claude, store, SETTINGS, NOW + timedelta(seconds=30))
    tick(gateway, store, SETTINGS, NOW + timedelta(seconds=30))
    assert len(gateway.sent) == sent  # a rerun sends nothing new


def test_a_move_and_a_note_in_one_email_are_one_update(live):
    store, gateway, threads = live
    claude = ScriptedClaude(
        [tool_use("change_event", start="2026-10-24T20:00"), tool_use("add_note", text="Bring wine", shareable=True)],
        [text("Done: 8 PM, and I'll ask everyone to bring wine.")],
    )
    host_says(store, gateway, threads, claude, "move to 8 and tell everyone to bring wine")

    group, d, reply = gateway.sent
    for message in (group, d):
        assert "(was 7 PM)" in message["body"] and "From Chris:\n- Bring wine" in message["body"]
    assert "Bring wine" in event(store, gateway)["description"]
    rows = store.db.execute("SELECT channel, recipient FROM outbox WHERE change_id IS NOT NULL ORDER BY id").fetchall()
    assert [tuple(row) for row in rows][-3:] == [("calendar", "event"), ("group", "group"), ("guest", D)]


def test_a_change_in_the_group_rides_on_butlers_reply(live):
    store, gateway, threads = live
    claude = ScriptedClaude(decide(True), [tool_use("change_event", start="2026-10-24T20:00")],
                            [text("Done, see you all at 8!")])
    host_says(store, gateway, threads, claude, "let's do 8 instead", channel="group", cc=(A, B))

    d, reply = gateway.sent
    assert (reply["to"], reply["cc"], reply["thread_id"]) == (HOST, [A, B], threads["group"])
    assert "see you all at 8!\n\nWhen: Saturday, October 24 at 8 PM (was 7 PM)" in reply["body"]
    assert "The calendar invite is updated." in reply["body"]
    assert d["to"] == D and "(was 7 PM)" in d["body"]
    assert "attached below your reply" in claude.requests[1]["system"]

    # Back in the Host thread, whose emails never mention 8 PM: the facts say where it moved (live, run hw1).
    claude = ScriptedClaude([text("It's at 8 PM now.")])
    host_says(store, gateway, threads, claude, "what time is it again?")
    facts = claude.requests[0]["messages"][0]["content"]
    assert "time Sat Oct 24, 7 PM → Sat Oct 24, 8 PM (in the group thread)" in facts


def test_private_notes_and_flips_only_touch_the_calendar(live):
    store, gateway, threads = live
    claude = ScriptedClaude(
        [tool_use("add_note", text="The cake is hidden in the garage", shareable=False)], [text("Saved, private.")],
        [tool_use("update_note", note_id=1, shareable=False)], [text("Parking is private now.")],
        [tool_use("update_note", note_id=3, delete=True)], [text("Forgotten.")],
    )
    calendar = event(store, gateway)
    calendar["description"] = "untouched"
    host_says(store, gateway, threads, claude, "the cake is hidden in the garage")
    assert calendar["description"] == "untouched" and store.notes(1)[-1]["shareable"] == 0

    host_says(store, gateway, threads, claude, "actually keep the parking note private")
    assert "Street parking" not in calendar["description"] and "Coming: 2" in calendar["description"]
    host_says(store, gateway, threads, claude, "forget the cake note")
    assert [note["text"] for note in store.notes(1)] == ["Street parking only", "Bob's surprise is a zeppelin ride"]
    assert [m["to"] for m in gateway.sent] == [HOST] * 3  # nobody else is emailed


def test_a_guest_invited_after_launch_gets_one_invite_and_nobody_else_hears(live):
    store, gateway, threads = live
    claude = ScriptedClaude([tool_use("invite_guest", email="E@example.com")], [text("Invited!")])
    host_says(store, gateway, threads, claude, "also invite E@example.com")

    invite, reply = gateway.sent
    assert (invite["to"], invite["cc"]) == ("e@example.com", [])
    assert "Saturday, October 24 at 7 PM" in invite["body"] and "Street parking only" in invite["body"]
    assert "zeppelin" not in invite["body"] and reply["to"] == HOST
    guest = store.guest(1, "e@example.com")
    assert (status(guest), guest["guest_thread_id"]) == ("invited", invite["thread_id"])


def test_cancel_needs_the_hosts_confirmation_in_their_next_email(live):
    store, gateway, threads = live
    claude = ScriptedClaude(
        [tool_use("ask_cancel_confirmation")], [text("Cancel it? Everyone will be told. Reply yes to confirm.")],
        [text("2 are coming, plus you.")],
        [tool_use("ask_cancel_confirmation")], [text("Sure? Reply yes.")],
    )
    host_says(store, gateway, threads, claude, "cancel the dinner")
    assert store.dinner(1)["status"] == "confirming_cancel" and [m["to"] for m in gateway.sent] == [HOST]

    host_says(store, gateway, threads, claude, "hmm, how many are coming?")  # not a yes: the question lapses
    assert "cancel_dinner" in [t["name"] for t in claude.requests[2]["tools"]]
    assert store.dinner(1)["status"] == "active"

    host_says(store, gateway, threads, claude, "ok, cancel it")
    assert "cancel_dinner" not in [t["name"] for t in claude.requests[3]["tools"]]
    assert store.dinner(1)["status"] == "confirming_cancel"


def test_cancel_tells_the_group_and_each_invited_or_attending_guest_outside_it_once(live):
    store, gateway, threads = live
    answers = event(store, gateway)["answers"]
    answers[B] = "declined"  # B declines on the calendar but stays in the Group thread
    tick(gateway, store, SETTINGS, NOW)
    gateway.sent.clear()
    claude = ScriptedClaude([tool_use("ask_cancel_confirmation")], [text("Sure? Reply yes.")],
                            [tool_use("cancel_dinner")], [text("Done. Everyone's been told.")])
    host_says(store, gateway, threads, claude, "we have to cancel")
    host_says(store, gateway, threads, claude, "yes")

    assert store.dinner(1)["status"] == "canceled"
    assert gateway.events == {} and gateway.invited == []  # deleted without Google's email
    _, group, d, reply = gateway.sent
    assert (group["to"], group["cc"]) == (HOST, [A, B])  # reaches B, Declined but in the group
    assert "Chris has canceled the dinner on Saturday, October 24 at 7 PM." in group["body"]
    assert (d["to"], d["thread_id"]) == (D, threads[D]) and "canceled" in d["body"]
    assert reply["to"] == HOST and to(gateway, C) == []

    sent = len(gateway.sent)
    gateway.receive(A, "oh no! what happened?", thread_id=threads[A])  # later emails are ignored
    poll_once(gateway, claude, store, SETTINGS, NOW + timedelta(seconds=30))
    tick(gateway, store, SETTINGS, NOW + timedelta(seconds=30))
    assert len(gateway.sent) == sent


def test_a_crash_mid_update_resends_only_what_was_not_sent(live):
    store, gateway, threads = live
    real_reply = gateway.reply
    d_invite = gateway.threads[threads[D]][0].message_id

    def flaky(message_id, *args, **kwargs):
        if message_id == d_invite:
            raise RuntimeError("Arcade down")
        return real_reply(message_id, *args, **kwargs)

    gateway.reply = flaky
    claude = ScriptedClaude([tool_use("change_event", place="34 Oak St")], [text("Moved to 34 Oak St.")])
    host_says(store, gateway, threads, claude, "we're doing it at 34 Oak St instead")
    assert [m["to"] for m in gateway.sent] == [HOST]  # the group got it; D's failed, so the Host's reply waits

    gateway.reply = real_reply
    poll_once(gateway, claude, store, SETTINGS, NOW + timedelta(seconds=30))
    assert [m["to"] for m in gateway.sent] == [HOST, D, HOST]
    assert "Where: 34 Oak St (was 12 Elm St)" in gateway.sent[1]["body"]
    assert event(store, gateway)["place"] == "34 Oak St"


def test_a_moved_dinner_closes_an_hour_after_its_new_start(live):
    store, gateway, threads = live
    claude = ScriptedClaude([tool_use("change_event", start="2026-10-24T20:00")], [text("Moved.")])
    host_says(store, gateway, threads, claude, "make it 8")
    eight = datetime(2026, 10, 24, 20, 0, tzinfo=ZONE)
    tick(gateway, store, SETTINGS, eight + timedelta(minutes=30))
    assert store.dinner(1)["status"] == "active"
    tick(gateway, store, SETTINGS, eight + timedelta(hours=1))
    assert store.dinner(1)["status"] == "closed"


# Tools


@pytest.fixture
def ctx(live):
    store, _, _ = live
    return Ctx(store, SETTINGS, 1, HOST, NOW)


def call(ctx, name, **args):
    return tools.TOOLS[name].call(ctx, args)


@pytest.mark.parametrize(
    "name, args, error",
    [
        ("change_event", {}, "new start, the new place"),
        ("change_event", {"start": "2026-10-01T19:00"}, "in the past"),
        ("invite_guest", {"email": A}, "already on the guest list"),
        ("invite_guest", {"email": HOST}, "is the Host"),
        ("invite_guest", {"email": "bob"}, "isn't an email address"),
        ("update_note", {"note_id": 9, "delete": True}, "No Host note"),
        ("update_note", {"note_id": 1}, "Pass shareable, or delete"),
        ("cancel_dinner", {}, "confirm first"),
    ],
)
def test_host_tools_reject_bad_input_without_writing(ctx, name, args, error):
    before = (dict(ctx.store.dinner(1)), [dict(g) for g in ctx.store.guests(1)], [dict(n) for n in ctx.store.notes(1)])
    with pytest.raises(ToolError, match=error):
        call(ctx, name, **args)
    assert before == (dict(ctx.store.dinner(1)), [dict(g) for g in ctx.store.guests(1)],
                      [dict(n) for n in ctx.store.notes(1)])


def test_get_guest_details_is_the_hosts_private_view(ctx):
    details = {guest["email"]: guest for guest in call(ctx, "get_guest_details")["guests"]}
    assert (details[C]["status"], details[C]["dietary_needs"]) == ("declined", "allergic to quince")
    assert (details[D]["status"], details[A]["in_group_thread"]) == ("invited", True)
