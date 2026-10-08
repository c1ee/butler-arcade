# Arcade feature proposal

Type: grilling
Mode: HITL
Status: resolved
Assignee: chrislee (session 2026-10-06)
Blocked by: 13

## Question

Which feature should Arcade add next, and why? Candidates: inbound triggers, first-class agent identities, audience-scoped tool access, exposing sender authentication (SPF/DKIM results) so agents can trust who an email is from, or a wall hit during the build. Pick one; state the problem, who hits it, evidence from this build, and a rough shape.

Lead candidate (from ticket 06): **audience-scoped tool access**. Motivation: Butler's domain tools gate access on who sent the email and who reads the reply, but Arcade auth is keyed on `user_id` (Butler). Exposed as Arcade tools, any MCP client holding Butler's id could call `get_guest_details`. So they stay app-internal.

## Answer

**Inbound triggers.** Main proposal only, no list of other gaps. Goes in WRITEUP as a section "Feature proposal for Arcade", linked from the top of README. The WRITEUP text ends at "Why only Arcade can build it" (user cut the sections after it).

**WRITEUP text (final):**

> ### Feature proposal: inbound triggers
>
> **Problem.** Arcade lets an agent act on a user's accounts but not hear from them. An agent that reacts to new email or calendar changes has to poll. Every email assistant, support-triage agent or scheduling agent built on Arcade writes the same loop.
>
> **Evidence from Butler.** Butler polls every 30 seconds: one `Gmail.SearchEmailsByQuery`, plus one `GoogleCalendar.GetEvent` per live Dinner to catch Guests answering the invite. With one Dinner that's 5,760 tool calls a day, almost all of them empty. The free plan's 2,000 calls a month would last about 8 hours. On the Team plan it would cost ~$1,700 a month for an agent that's mostly idle (we had unlimited take-home credits). Polling also costs code: a cursor, a 120-second re-read window because Gmail search indexes some emails late, and a calendar check every cycle. Replies wait up to 30 seconds.
>
> **Why only Arcade can build it.** Gmail push (`users.watch`) publishes to a Pub/Sub topic that must sit in the same Google project as the app making the call. On Arcade's default Google app, that project is Arcade's, so a developer can't set up Gmail push even if they want to. Arcade also already holds the user's token, so it can renew watches (Gmail's must be renewed at least every 7 days) and fetch what changed.

**Facts behind it (checked 2026-10-07):**
- No inbound triggers in Arcade's docs index (`docs.arcade.dev/llms.txt`). D7 still holds.
- Gmail `users.watch` `topicName`: the project id "must exactly match your Google developer project id (the one executing this watch request)". Watch lasts ≤7 days.
- Arcade pricing: Free 2,000 tool calls/month; Team $25/month + $0.01 per tool call.
- Butler's loop (`butler/main.py`, `butler/sync.py`): `SearchEmailsByQuery` every poll + `GetEvent` per live Dinner every poll, `OVERLAP_SECONDS = 120`. 2 calls/30s = 5,760/day ≈ 172,800/month ≈ $1,728.

**Why not audience-scoped tool access (the lead candidate):** Arcade already ships **Contextual Access**: developer-hosted webhooks on every tool call (access hook at tool listing, pre-execution, post-execution). Their payload carries only `user_id` (plus tool, inputs, output) per `ArcadeAI/schemas` `logic_extensions/http/1.0/schema.yaml`. For Butler that's always Butler. Adding app-supplied `sender`/`recipients` fields would only move Butler's own check into a webhook the same developer writes, since the Engine uses `user_id` just to pick the token. It adds value only if Arcade vouches for who's asking (delegated, policy-limited access to an agent's account) and sees the real readers. That's a bigger feature this build barely evidences, since Butler never had outside callers.

**Discussed, left out of WRITEUP (onsite talking points):**
- Shape: subscribe per user + event type, Arcade sets up and renews the provider's push. Webhook delivery plus a long-poll for agents without a public URL (Butler on a laptop, a reviewer's clone). At-least-once, dedupe by id. Events carry ids only, so every read still goes through a tool call (Contextual Access + audit still apply). Gmail + Calendar first; providers with push next; server-side polling for the rest.
- What triggers would and wouldn't change in Butler: the cursor, 120s window and per-poll calendar read go away. Dedupe stays, and so does telling Butler's own calendar edits from Guests' answers (its attendee adds fire "event changed" too).
- Revenue tension: polling earns Arcade $0.01/call. Price per delivered event; otherwise developers poll slowly or move to platforms with triggers (Composio has them).
- Sizing: Arcade's logs show users calling `SearchEmailsByQuery`/`ListEmails` on a regular timer.

Time: active time not tracked; session claimed 2026-10-06 18:59, closed 2026-10-07 ~14:57 (idle overnight).
