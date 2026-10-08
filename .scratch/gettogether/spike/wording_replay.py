"""Ticket 08: real Claude, fake Gmail. Do the new prompt lines hold? 3 runs per case.

uv run --project <repo> python -I wording_replay.py <repo>
"""

import dataclasses
import re
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, sys.argv[1])

import anthropic  # noqa: E402

from butler import config  # noqa: E402
from butler.main import poll_once  # noqa: E402
from tests import states  # noqa: E402
from tests.fakes import BUTLER, HOST, NOW, SETTINGS  # noqa: E402

real = config.load()
settings = dataclasses.replace(SETTINGS, anthropic_api_key=real.anthropic_api_key, model=real.model)
claude = anthropic.Anthropic(api_key=real.anthropic_api_key)
A = states.A

# (id, world, sender, thread, body, what the reply must not contain)
CASES = [
    ("setup", states.nothing_yet, HOST, "new",
     "Dinner at my place Sat 10/24 7pm, 482 Linden Ave. Invite a@example.com and b@example.com. Street parking "
     "only, tell guests.", r"(?i:send it|approve)|\bGuests\b|(?i:the host)"),
    ("guest_qa", states.invited, A, A, "Is there parking? And what's the dress code?", r"\bGuests\b|(?i:the host)"),
    ("group_move", states.planted, HOST, "group", "Butler, can we push it to 8:30?",
     r"(?i:calendar (invite )?(is |has been )?updated)|\bGuests\b|(?i:the host)"),
    ("host_move", states.planted, HOST, HOST, "move it to 8pm, and tell everyone to bring a bottle of wine",
     r"\bGuests\b|(?i:the host)"),
]


def run(case, n):
    name, build, sender, thread, body, banned = case
    world = build()
    store, gateway = world.store, world.gateway
    thread_id = None if thread == "new" else world.threads[thread]
    cc = ()
    if thread == "group":
        cc = tuple(m for m in store.members(1) if m != sender)
    email = gateway.receive(sender, body, thread_id=thread_id, cc=cc,
                            sender_name="Chris Lee" if sender == HOST else "Alice Park")
    poll_once(gateway, claude, store, settings, NOW)
    replies = [m for m in gateway.sent if m["thread_id"] == email.thread_id]
    text = replies[0]["body"] if replies else "(no reply)"
    own = text.split("Here's the draft:")[0].split("\n\nWhen:")[0]  # Claude's part, before any attached template
    hits = [m.group(0) for m in re.finditer(banned, own)]
    return name, n, hits, own.strip()


with ThreadPoolExecutor(6) as pool:
    results = list(pool.map(lambda args: run(*args), [(c, n) for c in CASES for n in (1, 2, 3)]))
for name, n, hits, own in results:
    print(f"=== {name} #{n} {'FAIL ' + str(hits) if hits else 'ok'}\n{own}\n")
print(f"{sum(not r[2] for r in results)}/{len(results)} clean")
