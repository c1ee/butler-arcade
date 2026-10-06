"""Group thread (H3, G4, G5, G7): starts at the threshold, welcomes later yeses, never loses a member, and Butler
speaks only when the should_speak gate says so."""

import json
from datetime import timedelta

import pytest

from butler import effects, tools
from butler.main import poll_once, tick
from butler.store import Store, status
from butler.tools import Ctx
from tests.fakes import BUTLER, HOST, NOW, SETTINGS, FakeGateway, ScriptedClaude, text, tool_use
from tests.test_guest import A, B, C, SECRETS, approved, event, on_calendar


def decide(speak: bool):
    return [text(json.dumps({"speak": speak, "reason": "scripted"}))]


def start_group(store: Store, gateway: FakeGateway) -> str:
    """A and B said yes (calendar awaiting), which starts the Group thread. Returns its thread id."""
    on_calendar(store, gateway, A, "needsAction")
    on_calendar(store, gateway, B, "needsAction")
    with store.transaction():
        effects.join_group(store, SETTINGS, 1, NOW)
    effects.flush(gateway, store)
    gateway.sent.clear()
    return store.dinner(1)["group_thread_id"]


def assert_no_secrets(claude: ScriptedClaude, gateway: FakeGateway, allowed=()):
    """Like tests/test_guest.py's, with A and B Attending: B's address is public, B's Guest note isn't."""
    seen = json.dumps([claude.requests, gateway.sent, list(gateway.events.values())], default=str)
    assert not [secret for secret in SECRETS if secret not in (B, *allowed) and secret in seen]


@pytest.fixture
def setup():
    store, gateway = Store(":memory:"), FakeGateway()
    return store, gateway, approved(store, gateway)


def test_the_second_yes_starts_the_group_thread_once(setup):
    store, gateway, threads = setup
    claude = ScriptedClaude([tool_use("record_rsvp", attending=True)], [text("You're in!")],
                            [tool_use("record_rsvp", attending=True)], [text("You're in!")])
    gateway.receive(A, "yes!", thread_id=threads[A], sender_name="August Lee")
    poll_once(gateway, claude, store, SETTINGS, NOW)
    assert store.dinner(1)["group_thread_id"] is None  # 1 of 2

    gateway.sent.clear()
    gateway.receive(B, "count me in", thread_id=threads[B], sender_name="Bea")
    poll_once(gateway, claude, store, SETTINGS, NOW)
    opener = next(m for m in gateway.sent if m["subject"].startswith("Group thread"))
    assert (opener["to"], opener["cc"]) == (HOST, [A, B])
    assert "Coming: 2 (August Lee, Bea)" in opener["body"] and "Reply all" in opener["body"]
    assert store.dinner(1)["group_thread_id"] == opener["thread_id"]
    assert store.members(1) == [HOST, A, B]

    assert_no_secrets(claude, gateway, allowed=["oboe"])  # B's own Guest note, in B's own thread
    assert "oboe" not in json.dumps([m for m in gateway.sent if m["to"] != HOST or m["cc"]])  # Host notices may

    gateway.sent.clear()
    with store.transaction():
        effects.join_group(store, SETTINGS, 1, NOW)  # nothing new: no second thread, no welcome
    effects.flush(gateway, store)
    assert gateway.sent == []


def test_a_later_yes_is_welcomed_into_the_group_with_current_facts(setup):
    store, gateway, threads = setup
    group = start_group(store, gateway)
    claude = ScriptedClaude([tool_use("record_rsvp", attending=True)], [text("Glad you can make it!")])
    gateway.receive(C, "actually I'm in!", thread_id=threads[C], sender_name="Cy")
    poll_once(gateway, claude, store, SETTINGS, NOW)

    welcome = next(m for m in gateway.sent if m["thread_id"] == group)
    # No member has posted yet: reply-all to Butler's opener, which is addressed to the Host.
    assert (welcome["to"], welcome["cc"]) == (HOST, [A, B, C])
    assert welcome["body"].startswith("Welcome, Cy! You're on the group thread now.")
    assert "Where: 12 Elm St" in welcome["body"] and "Coming: 3 (a@example.com, b@example.com, Cy)" in welcome["body"]
    assert store.members(1) == [HOST, A, B, C]
    # C is Attending now, so their address is public; their Dietary needs were shown only in their own thread.
    assert_no_secrets(claude, gateway, allowed=[C, "quince"])
    assert "quince" not in json.dumps([m for m in gateway.sent if m["to"] != HOST or m["cc"]])  # Host notices may


def test_the_welcome_replies_to_the_newest_member_post(setup):
    store, gateway, threads = setup
    group = start_group(store, gateway)
    claude = ScriptedClaude(decide(False), [tool_use("record_rsvp", attending=True)], [text("Yay!")])
    post = gateway.receive(B, "can't wait!", thread_id=group, cc=(HOST, A))
    gateway.receive(C, "I'm in after all", thread_id=threads[C])
    poll_once(gateway, claude, store, SETTINGS, NOW)

    welcome = next(m for m in gateway.sent if m["thread_id"] == group)
    assert (welcome["to"], welcome["cc"]) == (B, [HOST, A, C])
    assert store.newest_group_post(group, store.members(1))["gmail_message_id"] == post.message_id


def test_butler_stays_silent_on_chatter(setup):
    store, gateway, _ = setup
    group = start_group(store, gateway)
    claude = ScriptedClaude(decide(False))
    chatter = gateway.receive(A, "can't wait! 🎉", thread_id=group, cc=(HOST, B))
    poll_once(gateway, claude, store, SETTINGS, NOW)

    assert store.is_processed(chatter.message_id)
    assert gateway.sent == [] and len(claude.requests) == 1  # the gate only, no tool loop
    gate = claude.requests[0]
    assert gate["output_config"]["format"]["schema"]["required"] == ["speak", "reason"]
    assert "can't wait!" in gate["messages"][0]["content"] and "invited" not in gate["messages"][0]["content"]
    trace = store.db.execute("SELECT kind, output FROM trace").fetchall()
    assert [(row["kind"], json.loads(row["output"])["speak"]) for row in trace] == [("gate", False)]
    assert_no_secrets(claude, gateway)


def test_a_question_to_butler_gets_one_reply_to_the_whole_group(setup):
    store, gateway, _ = setup
    group = start_group(store, gateway)
    claude = ScriptedClaude(decide(True), [text("7 PM on Saturday!")])
    gateway.receive(A, "Butler, what time again?", thread_id=group, cc=(HOST, B))
    poll_once(gateway, claude, store, SETTINGS, NOW)

    (reply,) = gateway.sent
    assert (reply["to"], reply["cc"], reply["thread_id"]) == (A, [HOST, B], group)
    assert reply["body"].endswith("— Butler, on behalf of Chris")
    loop = claude.requests[1]
    assert [t["name"] for t in loop["tools"]] == ["get_event", "get_group_thread", "get_my_rsvp", "record_rsvp"]
    rsvp_tool = next(t for t in loop["tools"] if t["name"] == "record_rsvp")
    assert set(rsvp_tool["input_schema"]["properties"]) == {"attending", "plus_ones"}  # everyone reads the reply
    assert "group email thread" in loop["system"]
    assert_no_secrets(claude, gateway)


def test_dropping_out_in_the_group_keeps_them_in_it(setup):
    store, gateway, _ = setup
    group = start_group(store, gateway)
    with store.transaction():
        store.update_guest(1, A, dietary_needs="vegetarian")
    claude = ScriptedClaude(decide(True), [tool_use("record_rsvp", attending=False)], [text("Sorry to miss you!")])
    gateway.receive(A, "so sorry, can't make it anymore", thread_id=group, cc=(HOST, B))
    poll_once(gateway, claude, store, SETTINGS, NOW)

    assert status(store.guest(1, A)) == "declined" and A not in event(store, gateway)["attendees"]
    assert store.members(1) == [HOST, A, B]  # declines never remove anyone (D6)
    notice, reply = gateway.sent
    assert notice["to"] == HOST and "can't make it" in notice["body"]
    assert (reply["to"], reply["cc"]) == (A, [HOST, B])
    assert "vegetarian" not in json.dumps(claude.requests, default=str)  # A's own Dietary needs stay out of a group reply


def test_calendar_answers_start_the_group_but_never_shrink_it(setup):
    store, gateway, threads = setup
    on_calendar(store, gateway, A, "needsAction")
    on_calendar(store, gateway, B, "declined")
    answers = event(store, gateway)["answers"]

    answers[B] = "accepted"  # No → Yes on the calendar: 2 Attending
    tick(gateway, store, SETTINGS, NOW)
    group = store.dinner(1)["group_thread_id"]
    assert group and store.members(1) == [HOST, A, B]

    gateway.sent.clear()
    answers[B] = "declined"
    tick(gateway, store, SETTINGS, NOW + timedelta(seconds=30))
    answers[B] = "tentative"  # back again: no new welcome, they never left
    tick(gateway, store, SETTINGS, NOW + timedelta(seconds=60))
    assert gateway.sent == [] and store.members(1) == [HOST, A, B]


def test_a_plain_reply_to_butler_in_the_group_thread_is_private(setup):
    store, gateway, _ = setup
    group = start_group(store, gateway)
    claude = ScriptedClaude([tool_use("record_rsvp", attending=True, dietary_needs="no nuts")], [text("Noted!")],
                            decide(True), [text("Street parking only.")])
    gateway.receive(A, "Butler, I can't eat nuts btw", thread_id=group)  # To Butler only
    poll_once(gateway, claude, store, SETTINGS, NOW)
    notice, reply = gateway.sent
    assert notice["to"] == HOST and "no nuts" in notice["body"]
    assert (reply["to"], reply["cc"], reply["thread_id"]) == (A, [], group)
    assert store.guest(1, A)["dietary_needs"] == "no nuts"  # private: the Guest's own toolset
    assert "This is a Guest's private email thread" in claude.requests[0]["system"]

    gateway.sent.clear()
    gateway.receive(B, "what's parking like?", thread_id=group, cc=(HOST, A))
    poll_once(gateway, claude, store, SETTINGS, NOW)
    group_calls = json.dumps(claude.requests[2:], default=str)
    assert "nuts" not in group_calls and "Noted!" not in group_calls  # A's private emails stay out of the group
    (reply,) = gateway.sent
    assert (reply["to"], reply["cc"]) == (B, [HOST, A])


def test_the_host_in_the_group_gets_public_reads_only(setup):
    store, gateway, _ = setup
    group = start_group(store, gateway)
    claude = ScriptedClaude(decide(True), [text("Everyone: please bring a dish!")])
    gateway.receive(HOST, "Butler, remind everyone to bring a dish", thread_id=group, cc=(A, B))
    poll_once(gateway, claude, store, SETTINGS, NOW)

    (reply,) = gateway.sent
    assert (reply["to"], reply["cc"]) == (HOST, [A, B])
    assert [t["name"] for t in claude.requests[1]["tools"]] == ["get_event", "get_group_thread", "change_event",
                                                               "add_note", "invite_guest"]
    assert_no_secrets(claude, gateway)


def test_get_group_thread_shows_posts_but_not_private_emails(setup):
    store, gateway, _ = setup
    ctx = Ctx(store, SETTINGS, 1, A, NOW, gateway)
    assert "Not started" in tools.TOOLS["get_group_thread"].call(ctx, {})["group_thread"]

    group = start_group(store, gateway)
    gateway.receive(B, "can't wait!\n\nOn Tue Butler wrote:\n> Hi all", thread_id=group, cc=(HOST, A))
    gateway.receive(B, "psst Butler, I'm allergic to quince", thread_id=group)
    posts = tools.TOOLS["get_group_thread"].call(ctx, {})["posts"]
    assert [post["from"] for post in posts] == ["Butler", "b@example.com"]
    assert posts[1]["text"] == "can't wait!" and "quince" not in json.dumps(posts)


def test_replying_to_butlers_own_email_like_gmail():
    """Pins the fake to ticket 12's live check: why the welcome falls back to every_recipient."""
    gateway = FakeGateway()
    opener = gateway.send(HOST, "Group thread", "hi", cc=[A])
    gateway.reply(opener.message_id, "to the sender", cc=[A, B])
    gateway.reply(opener.message_id, "to everyone", cc=[HOST, A, B], to_sender_only=False)
    assert [(m["to"], m["cc"]) for m in gateway.sent[1:]] == [(BUTLER, [A, B]), (HOST, [A, B])]
