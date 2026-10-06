"""Privacy (D3, D12): the checks themselves, every tool on a planted Starting state, and one Dinner through every
send path with secrets planted. tests/conftest.py runs both checks after every test; these make sure they bite."""

import json
from datetime import timedelta

import pytest

from butler import tools
from butler.gateway import strip_quote
from butler.main import poll_once, tick
from butler.tools import Ctx, toolset
from tests import privacy, states
from tests.fakes import HOST, NOW, SETTINGS, FakeGateway, ScriptedClaude, text, tool_use
from tests.privacy import Secret
from tests.states import A, B, C, D, event
from tests.test_group import decide

# The checks catch what they should


def test_the_output_check_reads_recipients_and_gmails_quote():
    world = states.planted()
    gateway = world.gateway
    gateway.send(HOST, "Re: dinner", "Alice is allergic to kumquats")  # the Host may know
    gateway.send(A, "Re: dinner", "noted: allergic to kumquats")  # A's own
    gateway.send(B, "Re: dinner", "allergic to Kumquats")  # B may not
    note = gateway.add_to_thread(HOST, "remember: Bob's surprise is a zeppelin ride", world.threads[HOST])
    gateway.reply(note.message_id, "Noted, I'll loop Alice in", cc=[A])  # Gmail quotes the Host's email to A
    gateway.send(A, "Re: dinner", "Thaddeus can't come")  # a Declined Guest's identity
    gateway.send(A, "Re: dinner", "Thaddeusville is lovely")  # not a name: whole words only
    found = privacy.check(world.store, world.gateway, world.secrets)
    states.WORLDS.clear()  # planted on purpose
    assert found == [
        "output: ['kumquat'] in an email to ['b@example.com']: 'Re: dinner'",
        "output: ['zeppelin'] in an email to ['a@example.com', 'host@example.com']: 'Re: dinner'",  # quoted
        "output: ['Thaddeus'] in an email to ['a@example.com']: 'Re: dinner'",
    ]


def test_the_input_check_reads_traces_against_who_reads_the_answer():
    world = states.planted()
    store, gateway = world.store, world.gateway
    claude = ScriptedClaude([text("ok")], decide(True), [text("ok")], [text("ok")])
    emails = [gateway.receive(A, "hi", thread_id=world.threads[A]),
              gateway.receive(A, "hi all", thread_id=world.threads["group"], cc=(HOST, B)),
              gateway.receive(HOST, "hi", thread_id=world.threads[HOST])]
    poll_once(gateway, claude, store, SETTINGS, NOW)
    with store.transaction():
        for email in emails:  # as if a tool had returned this
            store.add_trace(email.message_id, 9, "tool", {"name": "spy"}, {"leak": "zeppelin, quince, kumquats"})
    found = privacy.check(store, gateway, world.secrets)
    states.WORLDS.clear()
    assert [line.split(" answering")[0] for line in found] == [
        "input: Claude was shown ['zeppelin', 'quince']",  # A may see A's own kumquats, not C's quince
        "input: Claude was shown ['zeppelin', 'quince', 'kumquat']",
    ]
    assert "read by ['a@example.com', 'b@example.com', 'host@example.com']" in found[1]


def test_replies_quote_like_gmail():
    """Pins the fake to ticket 05: a reply carries the replied-to email (its own quote included) below an attribution
    line, which strip_quote cuts off again."""
    gateway = FakeGateway()
    email = gateway.receive(A, "yes!\n\nOn Mon Butler wrote:\n> Can you make it?", sender_name="Alice Park")
    gateway.reply(email.message_id, "Great, see you there!")
    (sent,) = gateway.sent
    assert sent["quote"].startswith("\n\nOn Tue, Oct 6, 2026 at 1:00 PM Alice Park <a@example.com> wrote:\n\n> yes!")
    assert "> > Can you make it?" in sent["quote"]
    copy = gateway.threads[email.thread_id][-1]
    assert copy.body == sent["body"] + sent["quote"] and strip_quote(copy.body) == "Great, see you there!"


# Every tool, every toolset: no secret outside the audience of the reply it feeds


ARGS = {
    "update_draft": {"place": "34 Oak St"},
    "record_rsvp": {"attending": True, "plus_ones": 1},
    "change_event": {"start": "2026-10-24T20:00"},
    "add_note": {"text": "Bring wine", "shareable": True},
    "update_note": {"note_id": 1, "shareable": False},
    "invite_guest": {"email": "e@example.com"},
}

CONTEXTS = [  # role, channel, Dinner phase, sender
    ("host", "host_thread", "draft", HOST),
    ("host", "host_thread", "draft_shown", HOST),
    ("host", "host_thread", "active", HOST),
    ("host", "host_thread", "confirming_cancel", HOST),
    ("host", "group_thread", "active", HOST),
    ("guest", "guest_thread", "active", A),  # Attending
    ("guest", "guest_thread", "active", C),  # Declined
    ("guest", "guest_thread", "active", D),  # Invited
    ("guest", "group_thread", "active", A),
    ("guest", "group_thread", "active", B),
]


@pytest.mark.parametrize("role, channel, phase, sender", CONTEXTS)
def test_no_tool_returns_a_secret_its_readers_may_not_see(role, channel, phase, sender):
    def fresh():
        world = states.draft_shown() if phase in tools.SETUP else states.planted()
        with world.store.transaction():
            world.store.update_dinner(1, status=phase)
        return world

    names = toolset(role, channel, phase, attending=sender in (A, B))  # planted(): A and B are Attending
    assert names
    for tool in tools.registered(names, channel):
        world = fresh()  # each tool on its own Starting state
        store = world.store
        secrets = [*world.secrets, *privacy.identities(store)]
        readers = privacy.readers_of_answer(store, channel, sender, 1, HOST)
        ctx = Ctx(store, SETTINGS, 1, sender, NOW, world.gateway, "m-test")
        with store.transaction():
            output = tool.call(ctx, ARGS.get(tool.name, {}))
        assert privacy.leaks(json.dumps(output), readers, HOST, secrets) == [], tool.name


def test_every_tool_is_scanned():
    scanned = {name for role, channel, phase, sender in CONTEXTS
               for name in toolset(role, channel, phase, attending=sender in (A, B))}
    assert scanned == set(tools.TOOLS) | set(tools.GROUP_TOOLS)


# One Dinner through every send path, all secrets planted (the always-on check runs at the end)


def test_one_dinner_through_every_send_path():
    world = states.new_world(secrets=[Secret("zeppelin", HOST), Secret("quince", A), Secret("oboe", B),
                                      Secret("kumquat", C)])
    store, gateway, threads = world.store, world.gateway, world.threads
    clock = iter(range(0, 3600, 30))

    def email(sender, body, *responses, thread=None, cc=(), name=""):
        gateway.receive(sender, body, thread_id=thread, cc=cc, sender_name=name)
        poll_once(gateway, ScriptedClaude(*responses), store, SETTINGS, NOW + timedelta(seconds=next(clock)))

    # Setup: draft → preview → approve → calendar event (Host) + one private invite per Guest
    email(HOST, "dinner sat 10/24 7pm at 12 Elm St, invite a@ b@ c@ d@example.com. street parking only, tell guests. "
                "bob's surprise is a zeppelin ride",
          [tool_use("update_draft", start="2026-10-24T19:00", place="12 Elm St", add_guests=[A, B, C, D],
                    add_notes=[{"text": "Street parking only", "shareable": True},
                               {"text": "Bob's surprise is a zeppelin ride", "shareable": False}])],
          [text("Here's the draft.")], name="Chris Lee")
    threads[HOST] = store.dinner(1)["host_thread_id"]
    email(HOST, "send it", [tool_use("send_invites")], [text("Invites are out.")], thread=threads[HOST])
    invites = {m["to"]: m for m in gateway.sent if m["subject"].startswith("You're invited")}
    assert sorted(invites) == [A, B, C, D]
    threads |= {guest: invites[guest]["thread_id"] for guest in invites}

    # RSVPs: calendar adds, Host notices, the Group thread starting at the second yes
    email(A, "yes! I'm allergic to quince",
          [tool_use("record_rsvp", attending=True, dietary_needs="allergic to quince")], [text("See you there!")],
          thread=threads[A], name="August Lee")
    email(B, "count me in, leaving early for an oboe recital",
          [tool_use("record_rsvp", attending=True, note_for_host="leaving early for an oboe recital")],
          [text("You're in!")], thread=threads[B])
    email(C, "no, sorry. allergic to kumquats anyway",
          [tool_use("record_rsvp", attending=False, dietary_needs="allergic to kumquats")],
          [text("Thanks for letting me know!")], thread=threads[C], name="Thaddeus Quill")
    threads["group"] = store.dinner(1)["group_thread_id"]
    assert threads["group"] and store.members(1) == [HOST, A, B]

    # A Change from the Host thread: calendar, the group, and D (Invited) privately; C (Declined) hears nothing
    email(HOST, "push it back an hour", [tool_use("change_event", start="2026-10-24T20:00")], [text("Done.")],
          thread=threads[HOST])
    # A drops out in the group: off the calendar, Host notice, Butler's reply to the group
    email(A, "so sorry, can't make it anymore", decide(True), [tool_use("record_rsvp", attending=False)],
          [text("Sorry to miss you!")], thread=threads["group"], cc=(HOST, B))
    # B declines on the calendar: Headcount moves silently
    event(store, gateway)["answers"][B] = "declined"
    tick(gateway, store, SETTINGS, NOW + timedelta(seconds=next(clock)))
    # Cancel: ask, confirm, delete the event silently, tell the group and D
    email(HOST, "cancel it", [tool_use("ask_cancel_confirmation")], [text("Sure? Reply yes.")], thread=threads[HOST])
    email(HOST, "yes", [tool_use("cancel_dinner")], [text("Canceled.")], thread=threads[HOST])

    def where(message):
        thread = next((name for name, thread_id in threads.items() if thread_id == message["thread_id"]), "?")
        return f"{thread}: {message['to']}" + (f" cc {', '.join(message['cc'])}" if message["cc"] else "")

    sent = [where(message) for message in gateway.sent if not message["subject"].startswith("You're invited")]
    assert sent == [
        f"{HOST}: {HOST}",  # the draft
        f"{HOST}: {HOST}",  # invites are out
        f"{HOST}: {HOST}", f"{A}: {A}",  # A's yes: Host notice, reply
        f"{HOST}: {HOST}", f"group: {HOST} cc {A}, {B}", f"{B}: {B}",  # B's yes + the opener
        f"{HOST}: {HOST}", f"{C}: {C}",  # C's no
        f"group: {HOST} cc {A}, {B}", f"{D}: {D}", f"{HOST}: {HOST}",  # the Change
        f"{HOST}: {HOST}", f"group: {A} cc {HOST}, {B}",  # A drops out in the group
        f"{HOST}: {HOST}",  # are you sure?
        f"group: {A} cc {HOST}, {B}", f"{D}: {D}", f"{HOST}: {HOST}",  # canceled
    ]
    assert [email for _, email in gateway.invited] == [HOST, A, B]  # Google's invites: event created, two yeses
    assert gateway.events == {} and store.dinner(1)["status"] == "canceled"
