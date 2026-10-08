# GetTogether — PLAN

Arcade take-home (AI Engineer). 6h guideline (time tracked, not a hard cap). Deliverables: repo that clones + runs, short video, decisions writeup, one Arcade feature proposal.

Terms: `GLOSSARY.md` is canonical and overrides wording below (event → Dinner, pending → Invited, confirmed → Attending, party_size → Plus-ones, notes → Host note / Guest note). Execution is tracked in `.scratch/gettogether/map.md`.

## Problem

People stopped hosting dinner parties because the logistics are tedious: chasing RSVPs, collecting party sizes and dietary needs, answering the same questions, keeping everyone updated. **Butler** is an AI organizer with its own email address. Host and guests interact with it only by email — no app, no accounts, no OAuth for anyone but Butler.

## User stories (P0)

### Host
- **H1 Setup** — Host emails Butler free text ("dinner Sat 10/18 7pm at mine, invite a@, b@, c@"). Butler asks for anything missing, then replies with a draft invite.
  Required: date/time, place, guest emails. Optional: host note (e.g. what to bring), group threshold (default 2).
- **H2 Approve** — Host replies to approve. Butler creates the calendar event on its own calendar (start → start + 3h; host is attendee, guests are not) and sends each guest a private invite email.
- **H3 Group thread** — Once `threshold` guests say yes, Butler starts one group thread: host + confirmed guests + Butler. Later yeses are added with a templated welcome: current time, place, Headcount, who's coming. Butler never removes anyone from the Group thread; declines (email or calendar) leave membership unchanged. Threshold never reached → no group thread, everything stays private.
- **H4 Changes** — Host changes time/place, adds a shareable note, or invites more guests, from the private or group thread. One Host email = one update, however many changes it holds: Butler updates the calendar silently, posts once in the Group thread if it started (from the group, the update is attached to Butler's reply there), and privately tells each Invited or Attending Guest outside it (Invited ones are asked for a yes/no). New Guests get only their invite, with current details; inviting someone is never announced. The Host thread's facts list every Change and where it was made, so a Change from the group isn't "corrected" back (live, ticket 13).
- **H5 Ask anything** — Host asks questions ("who's coming?", "any allergies?"). Private thread: full access to all event state and notes. Group thread: public scope only, because guests read the answer (see D3).
- **H6 Notes** — Host tells Butler facts and whether guests may know them ("street parking only, tell guests" → shareable; "it's a surprise for Bob" → private). Unspecified → private. Shareable notes appear in the calendar description. Butler's reply says how each note was saved; the Host can flip or delete a note ("keep that private", "forget that note"), and the calendar description updates silently.
- **H8 Cancel** — Host thread only (in the group, Butler replies "please confirm with me privately"). Host asks to cancel → Butler calls `ask_cancel_confirmation` and asks to confirm, listing who will be told (`cancel_dinner` exists only for the Host's next message in the Host thread after Butler asked; any other message closes the window unless Butler asks again, D9). On confirm: one templated cancel post in the Group thread if it exists (it reaches every member, Declined ones included), and one private cancel message to each Invited/Attending Guest not in it; Declined Guests outside the group get nothing; no reason included; calendar event deleted without Google's email. Dinner becomes Canceled; later emails ignored.
- **Uninvite requests (H9 is fast follow)** — Butler replies that it can't remove Guests yet and suggests the Host tell them directly. Nothing changes.

### Guest
- **G1 RSVP** — Guest gets a private email and replies in free text. Classified yes/no only (no "maybe"). Yes → added as calendar attendee (receives calendar invite; shows as awaiting, which counts as coming, D13).
- **G2 Details** — Reply may include Plus-ones (→ public Headcount; email only, calendar "+N" ignored) and dietary needs / other notes (→ host-only). Default +1 policy in invite copy: "bring whoever you like, just tell us how many and we'll let the host know."
- **G3 Decline** — No → short private thank-you, nothing more. "Changed my mind, I'm in" later → treated as yes. If they had declined on the calendar, Butler silently removes and re-adds them: one fresh invite, shown as awaiting.
- **G4 Drop out** — Yes then no by email (private or group) → removed from calendar silently + short thank-you. They stay in the Group thread.
- **G5 Group etiquette** — Butler speaks in the group only when: the host instructs it, it's addressed directly, or it can answer a question from public facts. Otherwise silent. Guest requests to change the event are declined when addressed to Butler; otherwise silent. Any Guest in the Group thread, Declined or not, gets the group toolset; an RSVP change posted there counts (`record_rsvp`, bound to the sender) and always gets a reply. Everyone reads Butler's group replies, so there `get_my_rsvp`/`record_rsvp` neither show nor take Dietary needs or Guest notes. An email in the Group thread sent only to Butler (a plain Reply) is private: answered to the sender alone with their private toolset, and kept out of what Claude sees for group posts.
- **G6 Ask anything** — Guest asks questions in private or group ("what's parking like?", "who else is coming?"). Answered only from what guests may see (D3). Unknown → Butler says it doesn't know and suggests asking the Host directly.
- **G7 Calendar answers** — Attendees can answer with the invite's buttons. No → Declined: Headcount updates silently; they stay on the calendar (so they can switch back) and in the Group thread. Yes / Maybe / no answer → Attending (no new welcome when they switch back; they never left the group). No Host notice and nothing to the Guest either way (the Host can see the calendar); calendar notes aren't stored. Google's "Accepted:/Declined:" emails aren't conversation; the poll's calendar read catches the change.

### Lifecycle
Event is active from approval until **start + 1h** or until Canceled (H8); then Butler stops processing it.

## Out of scope

- **Fast follow:** nudges to non-responders (daily ×3, no host deadline); day-of logistics email; host-set +1 policy; Butler personality; multiple hosts/events; relay-style group thread (D6); cut 2026-10-06 to fit the time guideline: H7 Escalations (Butler forwards questions it can't answer and relays the Host's reply), H9 Uninvite, catch-up summary for late joiners, syncing the calendar's "+N" into Plus-ones (needs a which-channel-wins rule).
- **Not planned:** date finding, menu/potluck coordination, any UI.

## Architecture

**Role-scoped tool loop for conversation; deterministic workflow for everything else.** The model decides what to read and which domain action to take. Code decides who it is talking to, what it may see, who receives the reply, and how effects reach Gmail/Calendar.

```
poll Butler inbox (30s)
  → skip processed message ids
  → route: thread_id/sender → (event, channel ∈ {host_private, guest_private, group}, role ∈ {host, guest, stranger})
  → strip the quote the sender's mail app pasted; load the thread's last 10 messages via GetThread, each labeled by sender and stripped (D15)
  → group only: should_speak gate (structured call) → silent ⇒ done
  → tool loop with toolset(role, channel, event state), max 6 iterations
  → final text = reply; code sends it to the channel's recipients
  → write effects → outbox → send via Arcade → mark sent
  → mark message processed
tick: read each active Dinner's calendar event (GetEvent), diff attendee answers vs last snapshot → effects (D13)
tick: close events past start + 1h
```

### Information scopes

| Scope | Contents |
|---|---|
| `public` | time, place, confirmed headcount + names, shareable host notes (= calendar description + attendees) |
| `group` | group thread messages |
| `own` | the asking guest's RSVP, party size, dietary, notes |
| `private` | all guests' details, private notes, Invited/Declined list |

**Scope = min(asker, audience).** A reply in the group is read by guests, so host-in-group gets guest-level reads.

### Toolsets (role × channel)

Domain tools only — the model never sees raw Gmail/Calendar tools and never chooses recipients.

| Tool | Host thread | Host in Group thread | Attending Guest (own thread) or any Guest in Group thread | Invited or Declined Guest (own thread) |
|---|---|---|---|---|
| `get_event` (public) | ✓ | ✓ | ✓ | ✓ |
| `get_group_thread` | ✓ | ✓ | ✓ | |
| `get_my_rsvp` | | | ✓ | ✓ |
| `get_guest_details` (private) | ✓ | | | |
| `record_rsvp(attending, party_size?, dietary?, notes?)` — bound to sender | | | ✓ | ✓ |
| `change_event(start?, place?)` | ✓ | ✓ | | |
| `add_note(text, shareable)` | ✓ | ✓ | | |
| `invite_guest(email)` | ✓ | ✓ | | |
| `update_note(note, shareable? \| delete)` | ✓ | | | |
| `ask_cancel_confirmation()` — opens the cancel window (D9) | ✓ | | | |
| `cancel_dinner()` — only after Butler asked to confirm (D9) | ✓ | | | |

**Setup phase** (no approved event yet), host private only: `update_draft(start?, place?, guests?, note?, threshold?)`; `send_invites()` exists only once a complete draft has been shown to the host in an earlier message (D9).

### Other LLM calls (structured output, pydantic-validated)
- `should_speak(message, public facts, sender role) → {speak, reason}` — group gate, cheap, exact-match evaluable.

Invite emails, change notices, and the calendar description are **templates** (D8).

### State
- **Google Calendar (public source of truth):** time, place, who's coming (attendee answers, read every poll, D13), description rendered from `public` scope. Re-rendered on every change.
- **Calendar notifications:** only creating the event (Host gets the invite) and adding an attendee (only that Guest is emailed) use `all`. Every other update, removal, and delete uses `nobody`, because Butler sends its own notice. A `nobody` delete still takes the event off attendees' calendars (live, ticket 13).
- **SQLite (private):** events + draft, guests (status, party_size, dietary, notes, private thread_id), notes (text, shareable), group thread_id + members, processed message ids, outbox, loop traces (tool calls per message).

## Decisions (writeup material)

- **D1 Butler has its own Google identity.** One Arcade OAuth grant total. Arcade's default Google app requires authorizing users to be project members — delegating per host wouldn't work for real hosts without a custom OAuth app + custom user verifier. Butler owns the event; host is an attendee.
- **D2 Tool loop for conversation, workflow for effects.** Considered: one structured call with scoped context preloaded — enough for Q&A on state this small. Chose the loop because messages are compound ("yes! what's parking like?", "move to 8 and tell everyone to bring wine"), and because a per-role toolset *is* the permission model. Cost: latency + trajectory variance → iteration cap, traces, evals.
- **D3 Privacy by construction.** Scope = min(asker, audience). No tool available to a guest — or to anyone in the group — returns `private` data, so no prompt or injection can leak it.
- **D4 Identity bound by code.** `record_rsvp` has no guest parameter; it writes for the sender. Host-only tools aren't in a guest's toolset at all.
- **D5 Idempotent effects via outbox.** A change becomes outbox rows keyed `(change_id, channel, recipient)`; crash mid-propagation → rerun sends only unsent rows. Inbound dedupe by Gmail message id. Butler's reply to an email is an outbox row too: state changes + outbox rows + "message processed" commit in one transaction, sending happens after, so a crash can't double-reply or drop a reply.
- **D6 Group = plain reply-all (P0).** Email can't add/remove thread members; newcomers get a templated welcome with current facts instead of history. Butler adds Attending Guests and never removes anyone, so its cc list never reveals who declined (Uninvite, a fast follow, will be the first removal). Production alternative: relay (group `reply_to` = Butler address, Butler rebroadcasts to current members) → Butler owns membership, fixes late-join + drop-out, costs latency and sender identity.
- **D7 Polling, not push.** No inbound trigger found in Arcade. 30s poll; 30–60s latency accepted. Feature proposal: inbound triggers (wayfinder ticket 15).
- **D8 Templates for system messages, model for conversation.** Invites/notices/description are predictable and testable; replies to questions are where the model earns its keep.
- **D9 State-dependent toolsets.** Tools appear only when valid (e.g. `send_invites` after the draft was shown), so approval is enforced by code, not by prompt.
- **D10 Catalog only, no custom tool.** The live check showed catalog Gmail/Calendar cover every effect. There are two gaps: exact thread recipients (`ReplyToEmail` takes To from the replied-to message, quotes it, has no Reply-To) and sender authentication (no SPF/DKIM/DMARC exposed). Neither is P0. Group posts reply to the newest current member's message with `only_the_sender` + cc; until a member has posted, Butler reply-alls (`every_recipient`) its own newest post, because `only_the_sender` on its own email addresses Butler itself (live, ticket 12). Production: `ReplyInThread(to, cc, reply_to)` enables relay (D6); a DMARC check makes D4 trustworthy (forged `From` is out of scope for the demo).
- **D11 Evals in pytest, not `arcade evals` (yet).** Descoping first: evals with maximum control and quality, then decide what to offload to a platform. `arcade evals` scores only first-response tool calls (no loop, no reply), which is where privacy bugs live. Fast follow.
- **D12 Privacy checked on both sides.** Each planted secret has an owner; only Host + owner may see it. Input check: Claude is never shown a secret its reader may not see. Output check: nothing Butler sends (emails incl. Gmail's quoted text and derived recipients, Calendar event) carries one. Always on; zero tolerance; over-refusal fails too.
- **D13 Calendar decides who's coming.** Guests do decline on the calendar without telling anyone, so the attendee list and answers are the source of truth, read every poll. Butler can add/remove attendees but can't set a Guest's answer (catalog `RespondToEvent` answers only as Butler), so coming = on the calendar and not declined there (Yes, Maybe, or awaiting). Butler's own records hold only Guests not on the calendar (Invited, said no by email) plus a snapshot to diff. Email no → removed from calendar; email yes after a calendar No → remove + re-add. Considered: email-only RSVPs (two sources of truth), counting only calendar Yes (Guests RSVP twice), a custom tool to set answers (reopens D10; Google may ignore it for real accounts).
- **D14 One Dinner at a time (P0).** Writeup one-liner: every table is keyed by Dinner and threads map to one Dinner, so multiple Dinners mostly means routing fresh emails (a new Host thread starts a new draft; a Guest email that isn't a reply is matched by Dinner title, or Butler asks which one).
- **D15 Context from the real thread, not pasted quotes.** Claude sees the new message with the pasted quote stripped (Gmail and Outlook formats; whole email kept if neither is found), plus the thread's last 10 messages from Gmail, each labeled by its real sender. The pasted quote mixes old and new text and the sender can edit it (a fake "On Tue, [Host] wrote: …" is an injection); the real thread can't be forged and only holds what that thread's readers already received.

## Step 0 — Spike (before any code)

Verify with Butler's account:
1. `GoogleCalendar.UpdateEvent` can add/remove attendees **and** Google sends the invite (`sendUpdates`)?
2. Description updates — do they spam attendees with notifications?
3. `Gmail.ReplyToEmail` can reply-all **and** add new recipients (cc) in the same thread?
4. `Gmail.SendEmail` returns the `thread_id` we need to store?
5. Can domain tools be written with `arcade-mcp`'s tool decorator and evaluated by `arcade evals` locally (no deploy), using an Anthropic model? Yes → use it for tool-call evals. No → plain pytest. → Answered: partial; pytest only for P0 (D11).
6. Any Gmail/Calendar gap from 1–3 → custom tool via Arcade MCP; check how a reviewer runs it (`arcade deploy` vs local server). → Answered: catalog only (D10).

## Evals & tests (P0)

Full spec: `.scratch/gettogether/issues/07-eval-harness-decision.md`. Terms: GLOSSARY.md → Evals.

- **Harness:** pytest only. Live evals drive the real `agent.py` loop against fake Gmail/Calendar; record Claude inputs, tool calls, effects, reply. `uv run pytest` = deterministic (CI); `uv run pytest evals` = live, on demand, skips without key. 3 Runs per Eval case; results → `evals/RESULTS.md`.
- **Behavior evals** ~23, ≥90% — graded by outcome (state diff + queued emails + reply), not tool calls. Unlisted changes must be absent.
- **Leak evals** ~10, zero tolerance — attack set + Allowed facts that must be answered (over-refusal guard).
- **Speak/silent evals** ~15, ≥90% — exact match.
- **Privacy checks, always on** (every Run + every test). Calendar attendees may include Guests who declined on the calendar themselves (D13); Butler's own messages still never reveal who declined. input check (no secret shown to Claude outside its reader's audience) + output check (no secret in any email or the Calendar event outside its audience). Fake Gmail derives recipients and quotes like real Gmail.
- **Deterministic tests** (fake Arcade gateway): toolset matrix (role × channel × phase → exact tool names); every tool on a planted Starting state → no secret; one end-to-end Dinner through every send path with secrets planted; fake Gmail pinned to ticket 05 facts; `record_rsvp` writes only for sender; change → correct outbox rows; rerun → no duplicate sends; threshold crossing creates group once; Butler never removes a group member; lifecycle close at start + 1h and on cancel.

## Repo layout

```
butler/
  main.py        poll loop + tick
  config.py      ARCADE_API_KEY, ANTHROPIC_API_KEY, BUTLER_USER_ID, HOST_EMAIL, MODEL;
                 TIMEZONE = "America/Los_Angeles" constant (system-only, Butler never asks)
  gateway.py     only module that calls Arcade (fakeable seam)
  store.py       SQLite
  router.py      message → (event, channel, role)
  agent.py       tool loop (iteration cap, traces)
  tools.py       domain tools + toolset(role, channel, phase)
  gate.py        should_speak
  sync.py        per-poll calendar read: GetEvent, diff answers vs snapshot → Changes (D13)
  effects.py     change → outbox → send
  render.py      templates (emails, calendar description)
evals/         live evals (on demand) + RESULTS.md (committed)
tests/         deterministic tests (CI)
scripts/authorize.py   one-time Butler OAuth
README.md  WRITEUP.md
```

Stack: Python + uv, `arcadepy`, `anthropic`, `pydantic`, stdlib `sqlite3`, pytest. GitHub Actions runs deterministic tests. Model: `claude-sonnet-5-5` (configurable).

## Build order

Time spent is recorded in each ticket's Answer. Scope was cut on 2026-10-06 to land near the 6h guideline (see Out of scope); Cancel (H8) stays.

| # | Step | Done when |
|---|---|---|
| 0 | Spike | 6 questions answered |
| 1 | Skeleton: authorize script, gateway, store, poll loop, router | Butler logs every new message with route |
| 2 | Tool loop + toolset matrix + H1/H2 setup | Real event + private invites sent from an email conversation |
| 3 | Guest: `record_rsvp`, calendar add, Q&A (G1–G3, G6) | "yes! parking?" adds attendee + answers |
| 4 | Group: threshold, `should_speak`, welcome, G4/G5 | Group starts at threshold; Butler silent on chatter |
| 5 | Host writes + outbox + cancel (H4, H6, H8) | Change reaches calendar, group, pending guests once |
| 6 | Evals + tests | Pass rates printed; tests green |
| 7 | README, WRITEUP (incl. feature proposal), video | All 4 deliverables done |

**Least important P0 features, least first:** `invite_guest` after launch → G4 drop-out handling.

## Demo script (video, ~2–3 min)

1. Host emails partial details → Butler asks for place → host answers → draft → host approves.
2. Event on calendar (host only); guests A, B, C get private invites.
3. Host privately: "street parking only, tell guests. It's a surprise for B." → shareable + private notes.
4. A: "yes! bringing my partner, she's vegetarian — what's parking like?" → A on calendar, headcount 3, parking answered.
5. B: "yes" → threshold → group thread starts.
6. Group chatter → Butler silent. A in group: "Butler, any allergies we should know about?" → no private data.
7. Host privately: "any dietary needs?" → full answer. Host: "move to 8pm" → calendar, group, C all updated.
8. C: "sorry, can't make it" → thank-you. C: "actually I'm in!" → on calendar, added to the group with the welcome.
9. B clicks No on the calendar invite → Headcount in the description drops with no emails; B stays in the Group thread (D13).
10. Host privately: "cancel the dinner" → Butler asks to confirm → "yes" → each Guest gets one cancel message; event gone from calendars.

## Feature proposal candidates (picked: inbound triggers, wayfinder ticket 15)

- **Inbound triggers** (Gmail new message, Calendar RSVP change) so agents react instead of poll — every async agent hits this wall.
- **First-class agent identities** — agent-owned accounts as a supported pattern alongside on-behalf-of-user auth.
- **Audience-scoped tool access** — tool authorization keyed on who will *read* the output, not just who invoked the agent (D3 generalized).
- **Sender authentication** — expose SPF/DKIM/DMARC results so agents can trust who an email is from (D10).

## Confirmed assumptions

- Host asking in the group gets public scope only (D3).
- "Allowed information" for guests = shareable host notes; notes default to private.
- Pending guests can see confirmed names ("who else is coming?").
- Host gets a private notice on each email RSVP change (yes/no, Plus-ones, dietary). Calendar answers don't notify (D13).
- A guest emailing Butler fresh (not replying) routes to their private thread by sender address.
