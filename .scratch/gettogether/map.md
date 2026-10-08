# GetTogether — wayfinder map

Label: wayfinder:map

## Destination

GetTogether submitted to Arcade: a fresh repo that clones and runs, evals passing, README, WRITEUP (decisions + feature proposal), and a demo video — all four PDF deliverables, emailed to homework@arcade.dev.

## Notes

- **Execution override:** this map carries the build through submission, not planning only. Build tickets follow PLAN.md's build order.
- **Sources of truth:** `PLAN.md` (spec), `GLOSSARY.md` (terms; wins over PLAN.md wording), `Arcade Engineering Interview Project (1).pdf` (rubric). All at pstack root.
- **Skills:** grilling + domain-modeling for grilling tickets; research for research tickets; prototype for prototype tickets. Update `GLOSSARY.md` inline when terms shift.
- **Time:** 6h is a guideline, not a hard cap. Count from the spike onward (Arcade Gmail/Calendar capabilities and later). Record time spent in each ticket's Answer. Don't budget or cut the remaining steps to fit under 6h.
- **Timezone:** system constant `America/Los_Angeles` (PDT for the demo). Butler never asks.
- **Workspace vs repo:** map, research, spike scripts live in `pstack/.scratch/gettogether/` (private). Submission repo is a fresh `projects/gettogether/`, created in the skeleton ticket.
- **Secrets:** `.scratch/gettogether/.env` during spike; `.env` gitignored in the repo. Never commit keys.
- **Outward-facing actions need the user's OK:** emailing anyone beyond the demo accounts, publishing the repo, emailing homework@arcade.dev.
- **Reporting:** extremely concise.

## Decisions so far

<!-- one line per closed ticket: [title](issues/NN-slug.md): gist -->

- [Arcade Gmail + Calendar capabilities](issues/01-arcade-gmail-calendar-capabilities.md): catalog covers it with caveats. `UpdateEvent` adds/removes attendees but emails every guest on any update unless `send_notifications_to_attendees=nobody`; `CreateEvent` may not send the invite; `ReplyToEmail` reply-all + `cc` adds people in-thread but quotes the original; no tool sets Reply-To or exposes auth headers; poll via `SearchEmailsByQuery`. Calendar RSVP buttons are a second RSVP channel. 13 items → live check.
- [arcade evals fit for domain tools](issues/02-arcade-evals-fit.md): partial. Scores first-response tool calls from raw JSON schemas with Claude, no deploy; never runs tools or checks the reply text, so leak and loop evals need pytest. Pins `arcadepy==1.8.0`; exit code always 0.
- [Custom Arcade MCP tool runtime](issues/03-custom-mcp-tool-runtime.md): if a custom tool is needed, write it with arcade-mcp but call it in-process with Butler's token from `client.auth.start`, reusing the same Google grant. No extra steps for the reviewer. `tools.execute` only reaches deployed or tunneled workers, so `arcade deploy` is the optional production path.
- [Accounts and keys](issues/04-accounts-and-keys.md): Butler arrialee7 (Arcade owner), host campingchra, guests augustclee7 + xhakaout32 + guest.c.gettogether@outlook.com (no Arcade grant: default Microsoft app rejects personal accounts → C checked by hand). Keys in `.env`, both verified. All four accounts have Arcade Google grants. Gotcha: consent only completes when the browser's Arcade session = the `user_id` account.
- [Live check](issues/05-live-check.md): build facts confirmed. CreateEvent `all` sends the invite; add/remove notify only the affected guest; `nobody` is silent; reply threads map by thread_id; reply-all on own msg keeps To; `only_the_sender`+cc works for group (D6 upgrade viable). Pitfalls: comma `recipient` broken (spam/drop); invites are "from unknown sender" (not auto-added); "Accepted:/Declined:" mails + invite replies hit the inbox as new threads → router must handle; UpdateEvent returns a string. Outlook guest C: cc-add threads into one conversation, lands in Focused, replies and Accept reach Butler; Outlook's quote separator differs from Gmail's.
- [Custom tool decision](issues/06-custom-tool-decision.md): catalog only, no custom tool. Group posts: reply to the newest current member's msg with `only_the_sender` + cc (edge case with only Butler's opener → ticket 12). Faked sender out of scope (production line in WRITEUP). Domain tools stay app-internal. Production custom tools: `ReplyInThread(to, cc, reply_to)` for relay, DMARC check for D4.
- [Eval harness decision](issues/07-eval-harness-decision.md): pytest only (arcade evals = fast follow; descope, control first). Deterministic tests in CI; live evals on demand, 3 Runs, `evals/RESULTS.md` committed. Families: Behavior ≥90% (graded by outcome), Leak zero tolerance (+ over-refusal guard), Speak/silent ≥90%. Privacy: input + output checks always on, per-secret audience = Host + owner, fake Gmail mimics recipients + quoting. Added P0: Cancel (H8), Uninvite (H9), note check/fix (H6). Eval terms in GLOSSARY.
- [Calendar RSVP responses](issues/19-calendar-rsvp-channel.md): the calendar decides who's coming. Coming = on it and not declined there (Yes/Maybe/awaiting); Butler can't set answers, so email no → removed, email yes after calendar No → re-added. Calendar changes are silent (no Host notice). Declines never remove anyone from the Group thread (design review). Plus-ones email only.
- [Build skeleton](issues/09-build-skeleton.md): `projects/gettogether/` runs (commit 42e8903); `uv run butler` logs every new email's route (Dinner, channel, role) or why it's skipped. Gateway has every §3 method; store has dinner/guest/message/meta only. Aware datetimes → Butler's calendar tz irrelevant.
- [Build tool loop + Host setup](issues/10-build-tool-loop-setup.md): live setup works (commit 740d11d): Host emails → `update_draft` → Butler asks what's missing → preview (code-appended) → approve → Host-only calendar event + one private invite per Guest. `send_invites` only in `draft_shown`; any edit resets it. Reply + effects are outbox rows committed with "processed", flushed after. Loop: 6-call cap (last forced to answer), traces in SQLite. Non-setup emails still log-only.
- [Build Guest flow](issues/11-build-guest-flow.md): live (commit fbcbdc8): email yes → calendar attendee + Headcount in description + Host notice; no → removed silently + thank-you; calendar No/Yes moves Headcount silently via per-poll `sync`; email yes after calendar No → re-add. Effects from the net change per email. Q&A from preloaded public facts; unknown → ask the Host.
- [Build Group thread](issues/12-build-group-thread.md): live (commit eeaa392): threshold → opener (To Host, cc Attending); later yeses → welcome; members only grow. `should_speak` gate (structured output; Sonnet 5.5 rejects forced tool_choice) → silent on chatter. Group posts reply to newest member post (`only_the_sender` + cc), else reply-all to Butler's own (live: `only_the_sender` on own email addresses Butler). Group-thread email sent only to Butler = private, kept out of group context. Group RSVP tools omit Dietary needs/notes.
- [Build Host writes](issues/13-build-host-writes.md): live (commit d5208e8): one Host email = one Change: calendar (silent), one group post (or attached to Butler's group reply), one private notice per Invited/Attending Guest outside the group, invites for new Guests. Note flips silent. Cancel = ask → next Host email confirms; silent `DeleteEvent` removes it from attendees' calendars (verified). Host facts log every Change + where (fixes a live "correct it back" bug).
- [Email wording review](issues/08-email-wording-review.md): all 10 edits in (commit a49f050). Subjects carry the date, not the time; group subject "Everyone coming: …"; invite says yes → calendar invite; welcome says Reply all; Guests see first names. Prompts: lowercase "guests", never "the Host", no "send it" in the setup lead-in (replay 12/12). User renames demo Google display names before recording (→ 17).
- [Build evals + tests](issues/14-build-evals-tests.md): built (code f3b66d0, results 513a4e2). `uv run pytest`: 121 keyless deterministic tests + CI workflow (not yet run on GitHub). `uv run pytest evals`: 66 cases × 3 Runs, ~1.5 min, Anthropic key only → Behavior 105/105, Leak 42/42, Speak/silent 51/51, 0 privacy violations. Input + output checks are owner-aware and run on every test and Run. Fake Gmail quotes replies.
- [Record demo video](issues/17-demo-video.md): recorded, https://www.youtube.com/watch?v=bafARB1hod8 (**Private** → make Unlisted before submit). 9-step script ≤3 min (setup w/ parking note, A yes + diet, B yes → group, chatter silent, diets in group deferred to the Host, 8pm everywhere, Outlook C yes → welcome, cancel). Added `POLL_SECONDS`; group diet questions now "not allowed to share in the group, let [Host] answer" (Leak l15; evals 67 cases, 100%).
- [Arcade feature proposal](issues/15-feature-proposal.md): inbound triggers, main proposal only, WRITEUP section linked from README top; text ends at "Why only Arcade can build it". Evidence: idle Butler = 5,760 calls/day (free plan gone in ~8h, Team ~$1,700/mo) + polling-only code; only Arcade can do Gmail push on its default app (topic must be in the caller's Google project). Audience-scoped dropped: Contextual Access hooks exist but see only `user_id`, so app-supplied audience = relocated check.
- [README + WRITEUP](issues/16-readme-writeup.md): written (commit fc13d25). README: setup via Butler-owned Arcade account + `authorize.py`, run, tests vs evals, AI use; video link `TODO(link)`. WRITEUP: 8 decision sections + left out + production + proposal (unchanged). `docs/architecture.md` updated to as-built.

## Not yet specified

<!-- empty: build done; reviewer setup flow graduated into README + WRITEUP, demo logistics into Record demo video -->

## Out of scope

- Fast follows from PLAN.md: nudges, day-of logistics email, host-set +1 policy, Butler personality, multiple hosts/Dinners, relay-style Group thread. Beyond the submission.
- Date finding, menu/potluck coordination, any UI. PLAN.md "Not planned".
- Cut 2026-10-06 to land near the 6h guideline (Cancel kept): H7 Escalations, H9 Uninvite, catch-up summary for late joiners, syncing calendar RSVP buttons. Designs stay in PLAN.md as fast follows; WRITEUP's "what I left out" explains them.
