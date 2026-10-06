from datetime import UTC, datetime, timedelta

import pytest

from butler.main import OVERLAP_SECONDS, poll_once, tick
from butler.store import Store
from tests.fakes import HOST, NOW, SETTINGS, FakeGateway, ScriptedClaude, text, tool_use

A, B = "a@example.com", "b@example.com"


def test_each_email_is_handled_once_and_the_cursor_advances(caplog):
    caplog.set_level("INFO")
    store, gateway = Store(":memory:"), FakeGateway()
    gateway.receive(A, "hi")
    poll_once(gateway, None, store, SETTINGS, NOW)
    gateway.receive(B, "hello")
    poll_once(gateway, None, store, SETTINGS, NOW + timedelta(seconds=30))

    routed = [r.message for r in caplog.records if "→" in r.message]
    assert [line.split()[0] for line in routed] == ["m1", "m2"]
    assert all("skipped (unknown sender)" in line for line in routed)
    assert store.poll_cursor() == int(NOW.timestamp()) + 30


def test_poll_reads_from_before_the_cursor():
    store, gateway = Store(":memory:"), FakeGateway()
    searches = []
    gateway.search_inbox = lambda after: searches.append(after) or []
    poll_once(gateway, None, store, SETTINGS, NOW)
    poll_once(gateway, None, store, SETTINGS, NOW + timedelta(seconds=30))
    assert searches == [int(NOW.timestamp()) - OVERLAP_SECONDS] * 2


def test_setup_conversation_ends_in_a_calendar_event_and_private_invites():
    store, gateway = Store(":memory:"), FakeGateway()
    claude = ScriptedClaude(
        [tool_use("update_draft", start="2026-10-24T19:00", add_guests=[A, B])],
        [text("Sounds lovely! Where's it happening?")],
        [tool_use("update_draft", place="12 Elm St", add_notes=[{"text": "Street parking only", "shareable": True}])],
        [text("Got it. The parking note will be in the invite.")],
        [tool_use("send_invites")],
        [text("Done! Invites are out.")],
    )

    first = gateway.receive(HOST, "dinner Sat 10/24 7pm, invite a@example.com and b@example.com",
                            sender_name="Chris Lee")
    poll_once(gateway, claude, store, SETTINGS, NOW)
    dinner = store.dinner(1)
    assert (dinner["status"], dinner["host_thread_id"], dinner["host_name"]) == ("draft", first.thread_id, "Chris Lee")
    asked = gateway.sent[-1]
    assert (asked["to"], asked["thread_id"]) == (HOST, first.thread_id)
    assert "Where's it happening?" in asked["body"] and "Here's the draft" not in asked["body"]
    assert [tool["name"] for tool in claude.requests[0]["tools"]] == ["update_draft"]

    gateway.receive(HOST, "at mine, 12 Elm St. street parking only, tell guests", thread_id=first.thread_id)
    poll_once(gateway, claude, store, SETTINGS, NOW + timedelta(seconds=30))
    preview = gateway.sent[-1]["body"]
    assert store.dinner(1)["status"] == "draft_shown"
    assert "Saturday, October 24 at 7 PM" in preview and "Guests: a@example.com, b@example.com" in preview
    assert "You're invited: Dinner with Chris, Sat Oct 24, 7 PM" in preview
    assert preview.index("The parking note") < preview.index("Here's the draft")
    assert preview.endswith("— Butler")

    gateway.receive(HOST, "looks good, send it", thread_id=first.thread_id)
    poll_once(gateway, claude, store, SETTINGS, NOW + timedelta(seconds=60))
    assert [tool["name"] for tool in claude.requests[4]["tools"]] == ["update_draft", "send_invites"]
    dinner = store.dinner(1)
    assert dinner["status"] == "active"
    event = gateway.events[dinner["calendar_event_id"]]
    assert event["attendees"] == [HOST]
    assert event["end"] - event["start"] == timedelta(hours=3)
    assert "Street parking only" in event["description"]

    invites = [m for m in gateway.sent if m["subject"].startswith("You're invited")]
    assert [(m["to"], m["cc"]) for m in invites] == [(A, []), (B, [])]  # one private email each
    assert all("Street parking only" in m["body"] and A not in m["body"] and B not in m["body"] for m in invites)
    assert [store.guest(1, g)["guest_thread_id"] for g in (A, B)] == [m["thread_id"] for m in invites]
    assert gateway.sent[-1]["to"] == HOST and "Invites are out" in gateway.sent[-1]["body"]

    sent = len(gateway.sent)
    poll_once(gateway, claude, store, SETTINGS, NOW + timedelta(seconds=90))
    assert len(gateway.sent) == sent  # nothing new, nothing twice


def test_a_failed_send_is_retried_next_poll_without_rerunning_claude():
    store, gateway = Store(":memory:"), FakeGateway()
    claude = ScriptedClaude([text("Happy to help! When, where, and who?")])
    gateway.receive(HOST, "let's plan a dinner")
    real_reply = gateway.reply

    def down(*args, **kwargs):
        raise RuntimeError("Arcade down")

    gateway.reply = down
    poll_once(gateway, claude, store, SETTINGS, NOW)
    assert gateway.sent == [] and store.is_processed("m1")

    gateway.reply = real_reply
    poll_once(gateway, claude, store, SETTINGS, NOW + timedelta(seconds=30))
    assert len(gateway.sent) == 1 and len(claude.requests) == 1


def test_a_claude_failure_leaves_the_email_unprocessed():
    store, gateway = Store(":memory:"), FakeGateway()
    gateway.receive(HOST, "dinner?")
    with pytest.raises(IndexError):  # the script has no response: stands in for an API error
        poll_once(gateway, ScriptedClaude(), store, SETTINGS, NOW)
    assert not store.is_processed("m1") and store.current_dinner() is None and gateway.sent == []


def test_tick_closes_a_dinner_an_hour_after_it_starts():
    store = Store(":memory:")
    start = datetime(2026, 10, 24, 19, 0, tzinfo=UTC)
    with store.transaction():
        store.create_dinner(status="active", start_at=start.isoformat())
        store.create_dinner(status="draft", start_at=start.isoformat())
    tick(None, store, start + timedelta(minutes=59))
    assert store.dinner(1)["status"] == "active"
    tick(None, store, start + timedelta(hours=1))
    assert [store.dinner(1)["status"], store.dinner(2)["status"]] == ["closed", "draft"]
