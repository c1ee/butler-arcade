"""Replay the hw1 "Also invite C" email against the state just before it (start 8:30 from the group thread), with
the current prompt. Prints each Run's tool calls. Writes only to throwaway DB copies; sends nothing."""
import shutil
import sys
from dataclasses import replace
from datetime import UTC, datetime

import anthropic

from butler import agent, config, tools
from butler.gateway import Gateway
from butler.store import Store

MESSAGE = sys.argv[1] if len(sys.argv) > 1 else "1a11386d5659de68"
RUNS = int(sys.argv[2]) if len(sys.argv) > 2 else 3
settings = replace(config.load(), db_path="/tmp/hw_replay.db")
gateway, claude = Gateway(settings), anthropic.Anthropic(api_key=settings.anthropic_api_key)
for run in range(RUNS):
    shutil.copy("/tmp/butler_hw1.db", settings.db_path)
    store = Store(settings.db_path)
    with store.transaction():
        store.db.execute("UPDATE dinner SET start_at = '2026-10-24T20:30:00-07:00'")
        store.db.execute("DELETE FROM guest WHERE email LIKE '%outlook.com'")
        store.db.execute("DELETE FROM outbox WHERE change_id = 6 OR message_id = ?", (MESSAGE,))
        store.db.execute("DELETE FROM change WHERE id = 6")
        store.db.execute("DELETE FROM trace")
    dinner = store.dinner(1)
    email = next(e for e in gateway.get_thread(dinner["host_thread_id"]) if e.message_id == MESSAGE)
    earlier = agent.history(gateway, email, "host_thread", settings.butler_email)
    ctx = tools.Ctx(store, settings, 1, email.sender, datetime(2026, 10, 6, 23, 23, tzinfo=UTC), gateway, MESSAGE)
    with store.transaction():
        body = agent.answer(claude, settings.model, ctx, agent.Turn(email, "host", "host_thread", earlier))
    calls = store.db.execute("SELECT input FROM trace WHERE kind = 'tool' ORDER BY id").fetchall()
    print(f"Run {run + 1}: start {store.dinner(1)['start_at']} | tools {[c['input'] for c in calls]}\n  {body[:300]!r}")
