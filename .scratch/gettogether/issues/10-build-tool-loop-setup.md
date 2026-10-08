# Build tool loop + Host setup

Type: task
Mode: AFK
Status: resolved
Assignee: chrislee (session 2026-10-06)
Blocked by: 06, 09

## Question

PLAN.md build step 2. `agent.py` (iteration cap, traces), `tools.py` toolset(role, channel, phase) matrix, H1/H2: `update_draft`, draft preview, `send_invites` only after a complete draft was shown, Calendar event with Host only, private Guest invites via templates.
Done when: a real Dinner + private invites come out of an email conversation with the Host.

Design review 2026-10-06 (D15): every Claude call gets the new message with the pasted quote stripped (Gmail "On … wrote:" and Outlook "____ From:" formats; keep the whole email if neither is found) plus the thread's last 10 messages via `GetThread`, each labeled by sender and stripped. See `docs/architecture.md` §4.

From [Build skeleton](09-build-skeleton.md): build on `router.route()` → `Route`; `Route(None, "host_thread", "host")` means create the draft Dinner and set `host_thread_id`. Move `mark_processed` into the same `store.transaction()` as the effects + outbox rows (D5); add `host_note` / `change` / `outbox` / `trace` to `store.SCHEMA`. Gateway methods are ready, incl. `get_thread` (oldest first, Butler's own mail included). Pass timezone-aware datetimes (`config.TIMEZONE`).

## Answer

Done. Commit 740d11d on `main` (no co-author line). `uv run pytest`: 56 green.

- **Pipeline (`main.handle`):** only Host-thread emails while the Dinner is a draft reach the loop; everything else is still log + mark processed (TODO for 11–13). Host's first email creates the Dinner (`host_email`, `host_name` from the From display name, `host_thread_id`). `GetThread` runs before the transaction; then one transaction: loop + tool writes + draft preview + reply outbox row + `mark_processed`; `effects.flush` after, and again at the start of every poll (retries). Claude/API failure → rollback, email retried next poll.
- **`agent.py`:** `strip_quote` (Gmail/Apple "On … wrote:" incl. one wrapped line, Outlook `____`+From:, "Original Message"; whole email if none found or nothing left). `history()` = up to 10 thread emails *before* this one. Prompt: now (LA), situation facts (setup: draft JSON), earlier emails as `<email from="Host|Butler (you)|Guest x">`, then the new one. `run()`: max 6 Claude calls, last one `tool_choice=none` so it must answer; unknown tool / `ToolError` / pydantic error → `is_error` result back to Claude. Traces: step-1 input (system, content, tool names), every Claude output, every tool call + result.
- **`tools.py`:** full `toolset(role, channel, phase, attending)` matrix per PLAN (tested), registry `TOOLS` has only `update_draft` + `send_invites`. `update_draft(start, place, add_guests, remove_guests, add_notes[{text, shareable}], remove_notes, group_threshold)`; validates everything before writing; naive time → LA; any real change to a shown draft → status back to `draft`. `send_invites` refuses unless status `draft_shown` (so "looks good but make it 7:30" can't send). `show_draft()` appends the preview when the draft is complete and unseen, sets `draft_shown`.
- **`effects.py`:** `approve` → status active, title, Change `approve`, outbox rows: `create_event` (Host only, start → +3h, description) then one `invite` per Guest; `reply` row keyed by inbound message id. `flush` sends in id order, stops at first failure, commits each row's follow-up (`calendar_event_id`, `guest_thread_id`) with "sent".
- **`render.py`:** `when`/`short_when`/`clock` in LA, `title` = "Dinner with <Host first name>" (else "Dinner"), `sign` ("— Butler" to Host, "— Butler, on behalf of <first name>" to others), `invite`, `draft_preview`, `description(dinner, notes, coming, headcount, butler_email)`.
- **`store.py`:** + `dinner.host_email`, `dinner.host_name`; tables `host_note`, `change`, `outbox` (row = Change xor reply; partial unique indexes on (change, channel, recipient) and (message, channel, recipient)), `trace`. Delete `butler.db` after schema changes.
- **`gateway.Email`:** + `sender_name`.

**Live check (run tag tl1, script `spike/tl_check.py`):** Host "dinner Sat 10/24 7pm, invite A and B" → `update_draft(start, guests)`, Butler asks where. Host "482 Linden Ave, street parking only tell guests, surprise birthday for B keep it between us" → shareable + private note, preview shown (`draft_shown`). Host "looks good but make it 7:30, place is just 482 Linden Ave" → draft updated, **no** `send_invites`, new preview. Host "Perfect, send it!" → `send_invites`; calendar event (Host only, 7:30–10:30 PDT, Host got Google's invite), A and B each got one private invite (To only, parking note in, surprise absent), Host got "Done!". Event deleted afterwards (`nobody`), `butler.db` removed (copy `/tmp/butler_tl1.db`).

**New facts / leftovers:**
- Claude decorated `place` ("482 Linden Ave (Host's place)") and reworded a note ("keep it between the Host and Butler"); fixed with sharper field descriptions, not re-verified live.
- Claude still repeats "reply 'send it'" above the preview's own line despite the prompt → ticket 08 wording review.
- Butler's reply says "I sent the invites" while they're queued; true by the time the Host reads it (reply row is last).
- Anthropic SDK 1.11 logs via `httpx2`; silenced with `httpx`.
- Gmail plain-text bodies arrive hard-wrapped at ~76 chars; the prompt and `strip_quote` cope.

Time: ~20 min (13:27–13:47).

