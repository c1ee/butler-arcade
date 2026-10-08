# Build skeleton

Type: task
Mode: AFK
Status: resolved
Assignee: chrislee (session 2026-10-06)
Blocked by: 04, 05

## Question

PLAN.md build step 1. Create fresh repo `projects/gettogether/` (git init, uv, pyproject, .gitignore incl. .env, .env.example). Implement `scripts/authorize.py`, `config.py` (incl. TIMEZONE = America/Los_Angeles), `gateway.py` (only Arcade caller, fakeable), `store.py` (SQLite), poll loop in `main.py`, `router.py`.
Done when: Butler logs every new message with its route (Dinner, channel, role).

## Context for a cold session

Read first: `PLAN.md` (Architecture, Repo layout, D5, D10, D13), `GLOSSARY.md`, and the Answers of [Accounts and keys](04-accounts-and-keys.md) and [Live check](05-live-check.md). `spike/lc.py` shows working `arcadepy` usage (execute + logging).

- **Secrets:** copy `.scratch/gettogether/.env` into the repo as `.env` (gitignored). `.env.example` lists the keys without values. Never commit or print key values.
- **Auth:** Butler is already authorized (`BUTLER_USER_ID` = Butler's email). `authorize.py` requests the union scopes `gmail.send`, `gmail.readonly`, `calendar.events`, `calendar.readonly`, `calendar.settings.readonly`; `auth.start` returns `completed` immediately when already granted. Consent gotcha (04): the link only completes in a browser whose Arcade session is the same account as the `user_id`; print the link, don't auto-open it.
- **Polling (05):** `SearchEmailsByQuery` with `in:inbox after:<epoch>`; dedupe by message id (the `date` field is a display string). Field names differ from `GetEmail` (`message_id`/`sender` vs `id`/`from_`); normalize them in `gateway.py`.
- **Router (05, D13):** Google's "Accepted:/Declined:/Tentatively accepted:" emails (subject prefix, sent from the Guest's address, each a new thread) aren't conversation: route as calendar notifications and skip. A Guest replying to the calendar invite email arrives as a new thread: route by sender (+ Dinner title in the subject).
- **Gateway facts (05):** send with one `recipient` + `cc` (comma-separated `recipient` lands in spam or is dropped). `UpdateEvent` returns a string; re-read with `GetEvent`. Naive datetimes resolve in Butler's calendar tz (Pacific).
- **Toolchain:** uv 0.12.23, Python 3.14 on this machine. Catalog versions seen live: Gmail 8.12.1, GoogleCalendar 4.2.0.
- **Not in this ticket:** the per-poll calendar read and diff (D13) is built in the guest flow ticket; `main.py` just needs a tick hook for it.

## Answer

Done. Repo `projects/gettogether/` (committed 42e8903 on `main`, author Chris Lee <sychris.lee@gmail.com>, no co-author line). uv project `gettogether` (hatchling, package `butler`), Python ≥3.12, deps `arcadepy` 1.10.0, `anthropic` 1.11.0, `pydantic` 2.13.5; dev `pytest`. `.env` copied (600, gitignored); `.env.example` lists ARCADE_API_KEY, ANTHROPIC_API_KEY, BUTLER_USER_ID, HOST_EMAIL, optional MODEL.

- **Run:** `uv run butler` (`--once` = one poll); `uv run scripts/authorize.py`; `uv run pytest` (17 tests: router table, dedupe + cursor, close at start + 1h).
- **`config.py`:** `Settings` (frozen; tests build it directly), `load()` reads `.env`, real env wins. `butler_user_id` raw for Arcade, `butler_email` lowercase for matching. TIMEZONE, POLL_SECONDS=30, GOOGLE_SCOPES, DEFAULT_MODEL.
- **`gateway.py`:** every method in architecture §3 (search_inbox, get_thread, send, reply, create/get/update_event, add/remove_attendee, delete_event) → records `Email`, `Sent`, `Event`, `Attendee`. Raises `GatewayError`. Search uses `full` (10/page) with paging, oldest first. Only search + get_thread + get_event are exercised live by Butler code so far; sends use the params verified in ticket 05.
- **`store.py`:** tables `dinner`, `guest` (§7 columns), `message` (+ `sender`, `skipped`), `meta` (poll cursor). No `host_note` / `change` / `outbox` / `trace` yet: later tickets add them to `SCHEMA` (delete `butler.db` after schema changes). Writes need `with store.transaction()`.
- **`router.py`:** `route(email, store, settings) → Route(dinner_id, channel, role, skipped)`. Channels `host_thread` / `guest_thread` / `group_thread`; roles `host` / `guest` / `stranger` / `butler`. Known thread first, else current Dinner by sender. Skips: Butler's own email, calendar reply (`Accepted|Declined|Tentatively accepted|Tentative:` subject), unknown sender, canceled/closed Dinner, wrong person in a Host or Guest thread. Host with no current Dinner → `Route(None, "host_thread", "host")` = start a draft (ticket 10 creates it and sets `host_thread_id`). Invite replies route by sender only; the title check matters only with multiple Dinners (D14).
- **`main.py`:** `poll_once` re-reads 120s before the stored cursor (first run: from now), skips processed ids, routes, logs, marks processed. `tick()` closes active Dinners past start + 1h; it's the hook for `sync` (ticket 11). Poll errors are logged and retried next poll.

**Live check (run tag sk1/sk2, script `spike/sk_check.py`):** real `uv run butler` logged `new Dinner, host_thread, host` (Host fresh), `skipped (unknown sender)` (A, no Dinner), then with a seeded Dinner: `Dinner 1, host_thread, host` (Host reply in thread), `Dinner 1, guest_thread, guest` (A fresh), `skipped (calendar reply)` ("Accepted: …"). Restart caught up mail sent while Butler was down (cursor in SQLite). `authorize.py` → "already authorized". `butler.db` deleted afterwards.

**New facts:**
- `CreateEvent` / `UpdateEvent` accept offset-aware ISO datetimes (even UTC) and keep the instant, so the gateway sends aware datetimes and **Butler's calendar timezone setting doesn't matter** (one less README step).
- `GetThread` returns messages oldest first, Butler's own sent mail included; fields `id`/`from_` like `GetEmail`.
- Message and thread ids are per mailbox: the Host's sent copy has a different id from Butler's copy.
- Emails arriving in the same second are handled in Gmail's arrival order, not the senders' clocks.
- httpx logs every Arcade call at INFO; silenced.

Time: ~10 min (13:05–13:15).
