# Build Guest flow

Type: task
Mode: AFK
Status: resolved
Assignee: chrislee (session 2026-10-06)
Blocked by: 10, 19

## Question

PLAN.md build step 3. `record_rsvp` (bound to sender), Attending → calendar attendee, description re-render with Headcount, Declined thank-you, Declined → Attending, Guest Q&A from public scope (G1–G3, G6). Unknown answer → Butler says it doesn't know and suggests asking the Host directly (no Escalation). Calendar decides who's coming per [Calendar RSVP responses](19-calendar-rsvp-channel.md): per-poll `GetEvent` diff against a snapshot; email no → remove silently; email yes after a calendar No → remove + re-add; router skips Google's Accepted/Declined emails as conversation.
Done when: "yes! what's parking like?" adds the attendee and answers from a shareable Host note.

From [Build skeleton](09-build-skeleton.md): the router already skips "Accepted/Declined/Tentatively accepted/Tentative:" subjects; hook `sync` into `main.tick()`; `gateway.get_event()` returns `Event.attendees` with `response_status` + `additional_guests`.

From [Build tool loop + Host setup](10-build-tool-loop-setup.md): `main.handle` sends only setup-phase Host emails to the loop; open it to Guest threads. `agent.answer` raises `NotImplementedError` outside setup: add a Guest prompt section + facts, keep `BUTLER` as the base. Register `get_event`, `get_my_rsvp`, `record_rsvp` in `tools.TOOLS` (`toolset()` already lists them; `Ctx.sender` is the binding). Queue calendar writes as outbox rows in `effects.py` (add kinds to `_send`); `render.description(dinner, notes, coming, headcount, butler_email)` is ready. `guest.guest_thread_id` is Butler's mailbox thread from `SendEmail`. Reply rows: `effects.reply(store, email, channel, render.sign(body, dinner))` (Guest-facing signature takes the dinner). `tests/fakes.py` has `FakeGateway` + `ScriptedClaude`.

## Answer

Done. Commit fbcbdc8 on `main` (no co-author line). `uv run pytest`: 69 green (13 new in `tests/test_guest.py`).

- **Pipeline (`main.handle` → `converses()`):** Host thread in setup, or a Guest in their own Guest thread while the Dinner is live, go to the loop. Group thread and post-approval Host thread still log-only (TODO 12–13). Guest emails: display name → `guest.name`, snapshot the Guest row, run loop, then `effects.rsvp(store, settings, dinner_id, before)`, then reply signed on the Host's behalf.
- **`effects.rsvp`:** diffs the row before/after the whole email, so "yes! wait no" = one net change, one Host notice, no calendar churn. Queues in order: `add_attendee` / `remove_attendee` / `readd_attendee` (remove then add; Google resets the answer to awaiting) → `update_description` only if Headcount or who's coming moved → `host_notice` (only on status / Plus-ones / Dietary needs / Guest note change) → Butler's reply. Host notice = reply to `store.last_from(host_thread_id, host)` with `only_the_sender`. Calendar rows read `calendar_event_id` at send time.
- **`tools.py`:** `public_facts` (title, Host first name, when, place, shareable notes, Headcount, coming names; never Invited/Declined, per-Guest Plus-ones, Dietary needs, Guest notes, private notes), `own_rsvp`, tools `get_event`, `get_my_rsvp`, `record_rsvp(attending, plus_ones?, dietary_needs?, note_for_host?)`: writes for `ctx.sender` only; omitted field = unchanged, empty string = clear; refuses outside `LIVE`.
- **`agent.py`:** `GUEST` prompt section (clear yes/no only, maybe → ask; unknown → "don't know, ask <Host>"; only the Host changes the Dinner; decline → short thank-you). Public facts + own RSVP preloaded in the prompt (saves a step). Toolset filtered to registered tools (`get_group_thread` → 12).
- **`sync.py` (D13):** each poll (in `tick`, after close) `GetEvent` per live Dinner; snapshot answers for Guests Butler has on the calendar; Declined↔Attending move → Change `rsvp` (via calendar) + description only, no emails. Skipped while any outbox row is pending. Attendees Butler took off are ignored.
- **`store.py`:** `status(guest)`, `headcount(guests)`, `live_dinners()`, `last_from(thread, sender)`, `guest.name`. Delete `butler.db` (schema change).
- **`render.py`:** `guest_label`, `coming` ("Coming: 3 (August, Sang Lee + 1 more)": total only, per-Guest Plus-ones stay own scope), `host_notice`.
- **Decline thank-you is Claude's reply, not a template** (conversation, D8); ticket 08's template list is one shorter.

**Live check (run tag gf1, script `spike/gf_check.py`, log `/tmp/butler_gf1.log`, db `/tmp/butler_gf1.db`):** Host one-shot setup → preview → "send it" → invites. A: "yes! bringing my partner, she's vegetarian. what's parking like?" → A on calendar (Google invite to A only), description "Coming: 2 (August + 1 more)", Host notice (vegetarian, +1, Headcount 2), reply quotes "street parking only". **Done-when met.** B "yes" → added. B clicks No (RespondToEvent as B) → Google's "Declined:" email skipped; next tick: B Declined, description back to 2, zero emails, B still on the event. B replies to Google's invite email "I'm in after all" (new thread, routed by sender) → remove + re-add: B awaiting, one fresh Google invite, no cancel email; Headcount 3. A "dress code?" → "don't know, ask Camping". A drops out → removed silently (no Google email), thank-you, Host notice, Headcount 1. Event deleted (`nobody`) afterwards.

**Leftovers:**
- Q&A replies still restate dinner facts and say "the Host" despite a prompt line → ticket 08.
- Host display name comes from Gmail ("Camping"); test account names are odd on screen (B = "Sang Lee") → demo (17).

Time: ~20 min (14:04–14:24).
