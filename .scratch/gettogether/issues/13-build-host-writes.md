# Build Host writes, outbox, cancel

Type: task
Mode: AFK
Status: resolved
Assignee: chrislee (session 2026-10-06)
Blocked by: 12

## Question

PLAN.md build step 5. `change_event`, `add_note`, `invite_guest`; outbox keyed (change_id, channel, recipient); Changes reach Calendar event, Group thread, and Invited Guests exactly once; lifecycle close at start + 1h (H4, H6, H8).
Added by ticket 07: `update_note` (flip/delete; reply states how a note was saved), `cancel_dinner` after Butler asked to confirm (H8). Cut 2026-10-06: Escalations (H7) and `uninvite_guest` (H9); an uninvite request gets "I can't remove guests yet, please let them know directly". Verify live: does `DeleteEvent(send_updates="nobody")` still remove the event from guests' calendars?
Done when: a Change reaches every channel once, and a rerun sends nothing new.

Design review 2026-10-06: cancel = one post in the Group thread if it exists (reaches every member, Declined included) + one private message to each Invited/Attending Guest not in it; Declined Guests outside the group get nothing.

From [Build tool loop + Host setup](10-build-tool-loop-setup.md): the Host thread after approval is still log-only in `main.handle`; this ticket adds the active-phase Host prompt and registers `get_guest_details`, `change_event`, `add_note`, `invite_guest`, `update_note`, `cancel_dinner` (names already in `toolset()`). Outbox has `change` rows + partial unique indexes; `effects.approve` is the pattern for fanning a Change out.

From [Build Guest flow](11-build-guest-flow.md): `effects.update_description(store, settings, dinner_id, change_id)` re-renders from current state; calendar outbox rows read `calendar_event_id` at send time. Kinds in `effects._send`: `add_attendee`, `remove_attendee`, `readd_attendee`, `update_description`, `host_notice`. `sync` skips while any outbox row is pending.

From [Build Group thread](12-build-group-thread.md): the Host in the Group thread already goes gate → loop with `agent.GROUP` (public facts) and whatever `tools.registered` finds, so registering `change_event`/`add_note`/`invite_guest` lights them up there; add their lines to `GROUP`. Change notice and cancel posts: reuse `effects._post_in_group(gateway, store, dinner_id, body, members)` (computes To/cc at send time; members from `store.members`). A Host email in the Group thread sent only to Butler routes to `host_thread`. `GROUP` already says "confirm cancel privately". `invite_guest` after launch: a new Guest's yes reaches `effects.join_group` like any other.

## Answer

Done. Commit d5208e8 on `main` (no co-author line). `uv run pytest`: 105 green (16 new in `tests/test_host.py`, 5 in `test_agent.py`).

- **Pipeline (`main.handle`):** the Host thread always reaches the loop now (router already skips Dinners that are over). Host email while live: `effects.snapshot` before the loop → `effects.host_changes(store, settings, dinner_id, before, in_group)` after → `tools.lapse_cancel` (Host thread only).
- **One email = one Change (`effects.host_changes`):** diffs start, place, notes, guests. Queues one `update_event` row (start/end/place/description, `nobody`), then the update (`render.change_lines`: current When/Where with "(was …)", new shareable notes) to `effects.audience`: the Group thread if it started (Declined members included) + each Invited/Attending Guest outside it (Invited ones get "Can you make it?"). From the Group thread the update is attached to Butler's reply instead of a second post. New Guests get only their invite (rendered after all changes, so current). Flips/deletes and private notes: calendar description only, nobody emailed. Nothing to do → no Change row.
- **Tools:** `get_guest_details`, `change_event(start?, place?)`, `add_note(text, shareable)`, `update_note(note_id, shareable? | delete)`, `invite_guest(email)`, `ask_cancel_confirmation()`, `cancel_dinner()`. Tools write state only. Shared validation: `tools.local_start`, `tools.check_guest_address`.
- **Cancel (D9):** `ask_cancel_confirmation` sets `confirming_cancel` + `dinner.cancel_asked_in = message id` and returns who would be told. `cancel_dinner` is offered only in the next Host-thread email; `lapse_cancel` resets to `active` after any Host-thread email that neither canceled nor asked again. `effects.cancel`: `delete_event` (`nobody`) → one group post → one private message per Invited/Attending Guest outside the group; Declined outside get nothing. Router then skips everything for that Dinner.
- **Private notices** go in the Guest thread: reply-all (`every_recipient`) to Butler's invite, which is To that Guest only (`effects._post_to_guest`, reads the thread via `GetThread`).
- **Host prompt (`agent.HOST`)** with private facts (`tools.host_facts`: guests with details, notes with ids, `changes_since_invites` log), `CANCEL_ASKED` line in the window, `GROUP_HOST` lines for the Host in the group. Uninvite request → "can't remove guests yet, tell them directly" (prompt only).
- **Schema:** `dinner.cancel_asked_in`; Change kinds `change` / `cancel`. Delete `butler.db`.

**Live check (run tag hw1, script `spike/hw_check.py`, log `/tmp/butler_hw1.log`, db `/tmp/butler_hw1.db`, threshold 1):** setup → send → A yes → group (Host + A). Host thread "move it to 8pm, and tell everyone to bring a bottle of wine" → `change_event` + `add_note` → calendar 8–11 PM + wine in description, 1 group post, 1 private notice to B (Invited) in B's invite thread, both changes in one email. Host reply-all in group "make it 8:30" → update attached to Butler's group reply, B private. Host "also invite C" → C's invite (To C only, current details). Host "keep the parking note private" → description updated, only the Host's reply. Host "need to cancel" → asked, listing who'd be told → "Yes, cancel it." → event deleted, 1 group post (Host + A), private to B and C, Host reply. A's later group reply → skipped (Dinner canceled). **Verify-live answered: `DeleteEvent(send_updates="nobody")` removes the event from attendees' calendars (A's and the Host's `ListEvents` empty) and Google sent no "Canceled" or "Updated invitation" email for 3 time changes + delete** (only the 2 original invites). **Done-when met.**

**Bugs found live, fixed:**
- On "also invite C", Claude also moved the time back from 8:30 to 8 PM: the 8:30 change was made in the Group thread, so the Host thread's emails still said 8 PM and Claude "corrected" the facts. Fix: `changes_since_invites` (each Change + where it was made, from new `change` payload fields `start`, `place`, `via`) + prompt line "never change anything this email doesn't ask for". Replayed the same email 3× against the rolled-back state (`spike/hw_replay.py`): 3/3 only `invite_guest`, time kept.
- Host got "— Butler" twice: Claude copied the signature from Butler's earlier emails. `render.sign` now drops a trailing signature Claude wrote (tests). Live after restart: single signature.

**Leftovers:**
- Subjects keep the old time ("Group thread: … Sat Oct 24, 7 PM", "You're invited: … 7 PM") because `ReplyToEmail` can't change a subject → 08 / WRITEUP.
- Not re-verified live: Claude repeating "the calendar invite is updated" above the attached group update (prompt now says it's attached), and Host replies recapping the dinner (new "keep it short" line) → 08.
- Gmail search lags a few seconds after a send; spike scripts that search right after sending can miss (`hostreply` IndexError once).

Time: ~25 min (16:04–16:29).
