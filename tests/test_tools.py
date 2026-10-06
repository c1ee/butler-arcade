import json

import pytest

from butler import tools
from butler.store import Store
from butler.tools import Ctx, ToolError, toolset
from tests.fakes import HOST, NOW, SETTINGS

HOST_THREAD = ["get_event", "get_group_thread", "get_guest_details", "change_event", "add_note", "invite_guest",
               "update_note", "ask_cancel_confirmation"]


@pytest.mark.parametrize(
    "role, channel, phase, attending, expected",
    [
        ("host", "host_thread", "draft", False, ["update_draft"]),
        ("host", "host_thread", "draft_shown", False, ["update_draft", "send_invites"]),
        ("host", "host_thread", "active", False, HOST_THREAD),
        ("host", "host_thread", "confirming_cancel", False, HOST_THREAD + ["cancel_dinner"]),
        ("host", "group_thread", "active", False, ["get_event", "get_group_thread", "change_event", "add_note",
                                                   "invite_guest"]),
        ("host", "group_thread", "confirming_cancel", False, ["get_event", "get_group_thread", "change_event",
                                                              "add_note", "invite_guest"]),
        ("guest", "guest_thread", "active", True, ["get_event", "get_group_thread", "get_my_rsvp", "record_rsvp"]),
        ("guest", "guest_thread", "active", False, ["get_event", "get_my_rsvp", "record_rsvp"]),
        ("guest", "group_thread", "active", False, ["get_event", "get_group_thread", "get_my_rsvp", "record_rsvp"]),
        ("guest", "guest_thread", "draft", False, []),
        ("stranger", "guest_thread", "active", False, []),
    ],
)
def test_toolset(role, channel, phase, attending, expected):
    assert toolset(role, channel, phase, attending) == expected


@pytest.fixture
def ctx():
    store = Store(":memory:")
    store.create_dinner(host_email=HOST, host_name="Chris Lee")
    return Ctx(store, SETTINGS, 1, HOST, NOW)


def call(ctx, name, **args):
    return tools.TOOLS[name].call(ctx, args)


def test_update_draft_reads_local_time_and_reports_what_is_missing(ctx):
    draft = call(ctx, "update_draft", start="2026-10-24T19:00", add_guests=["A@example.com", "a@example.com"])
    assert ctx.store.dinner(1)["start_at"] == "2026-10-24T19:00:00-07:00"
    assert draft["start"] == "2026-10-24T19:00 (Saturday, October 24 at 7 PM)"
    assert draft["guests"] == ["a@example.com"]
    assert draft["missing"] == ["place"]


@pytest.mark.parametrize(
    "args, error",
    [
        ({"start": "2026-10-01T19:00"}, "in the past"),
        ({"add_guests": ["bob"]}, "isn't an email address"),
        ({"add_guests": [HOST]}, "is the Host"),
        ({"add_guests": ["butler@example.com"]}, "is the Butler"),
        ({"remove_guests": ["nobody@example.com"]}, "Not on the draft"),
        ({"remove_notes": [7]}, "No Host note"),
        ({"group_threshold": 0}, "greater than or equal to 1"),
    ],
)
def test_update_draft_rejects_bad_input_without_writing(ctx, args, error):
    with pytest.raises(ToolError, match=error):
        call(ctx, "update_draft", place="12 Elm St", **args)
    assert ctx.store.dinner(1)["place"] is None


def test_send_invites_needs_the_complete_draft_shown_first(ctx):
    call(ctx, "update_draft", start="2026-10-24T19:00", place="12 Elm St", add_guests=["a@example.com"])
    with pytest.raises(ToolError, match="hasn't seen this version"):
        call(ctx, "send_invites")
    assert "Here's the draft" in tools.show_draft(ctx.store, 1)
    assert tools.show_draft(ctx.store, 1) is None  # shown once per version
    assert call(ctx, "send_invites")["invited"] == ["a@example.com"]
    with pytest.raises(ToolError, match="already went out"):
        call(ctx, "send_invites")
    with pytest.raises(ToolError, match="already went out"):
        call(ctx, "update_draft", place="elsewhere")


def test_editing_a_shown_draft_takes_send_invites_away_until_shown_again(ctx):
    call(ctx, "update_draft", start="2026-10-24T19:00", place="12 Elm St", add_guests=["a@example.com"])
    tools.show_draft(ctx.store, 1)
    call(ctx, "update_draft", place="12 Elm St")  # no real change: still approvable
    assert ctx.store.dinner(1)["status"] == "draft_shown"
    call(ctx, "update_draft", start="2026-10-24T19:30")  # "looks good but make it 7:30"
    with pytest.raises(ToolError, match="hasn't seen this version"):
        call(ctx, "send_invites")
    assert "7:30 PM" in tools.show_draft(ctx.store, 1)


def test_incomplete_draft_is_not_shown(ctx):
    call(ctx, "update_draft", start="2026-10-24T19:00", add_guests=["a@example.com"])
    assert tools.show_draft(ctx.store, 1) is None


def test_private_notes_stay_out_of_the_invite_and_calendar(ctx):
    call(ctx, "update_draft", start="2026-10-24T19:00", place="12 Elm St", add_guests=["a@example.com"],
         add_notes=[{"text": "Street parking only", "shareable": True},
                    {"text": "It's a surprise for Bob", "shareable": False}])
    preview = tools.show_draft(ctx.store, 1)
    assert "It's a surprise for Bob (private: only you see it)" in preview
    call(ctx, "send_invites")
    payloads = [json.loads(row["payload"]) for row in ctx.store.pending()]
    assert [p["kind"] for p in payloads] == ["create_event", "invite"]
    assert all("surprise" not in json.dumps(p) and "Street parking only" in json.dumps(p) for p in payloads)
