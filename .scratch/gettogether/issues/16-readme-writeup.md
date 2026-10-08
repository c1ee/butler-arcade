# README + WRITEUP

Type: task
Mode: AFK
Status: resolved
Assignee: chrislee (session 2026-10-07)
Blocked by: 14, 15

## Question

README: what it is, prerequisites, setup (incl. Butler authorization), run, evals, external resources + how LLMs/coding agents were used. WRITEUP: interesting decisions + tradeoffs + what was left out (PLAN.md D1–D10 as source, not a changelog), what changes for production, the feature proposal.

Ship `pstack/docs/architecture.md` as `docs/architecture.md` in the repo (update it to match what was built; link it from README and WRITEUP). `docs/build_html.py` is a local review viewer and stays in pstack.

WRITEUP must include the D14 one-liner on extending to multiple Dinners (PLAN.md D14).

From [Email wording review](08-email-wording-review.md): WRITEUP tradeoff: `ReplyToEmail` can't set a subject, so subjects carry only the date (a date change still leaves them stale; production: a custom reply tool with a subject). Guests see each other by first name only.

From [Build evals + tests](14-build-evals-tests.md): README evals section: `uv run pytest` (no keys, CI) vs `uv run pytest evals` (Anthropic key only, ~1.5 min, `--runs 1` / `--case`), link `evals/RESULTS.md`. WRITEUP: 07's eval paragraph, plus the honest caveat that Leak passes mostly by construction (D3) and 100% confirms the design rather than stressing it.

Graduated from the map's fog (build done): **reviewer setup flow.** README walks a reviewer through provisioning a Butler Gmail, a Host account and at least one Guest account, Arcade + Anthropic keys, and `authorize.py` (catalog scopes only, no custom tool runtime; consent link must open in a browser logged into Arcade as that same account, see Accounts and keys). No calendar-timezone step (gateway sends offset-aware datetimes). `uv run pytest` needs no keys; `uv run pytest evals` needs only `ANTHROPIC_API_KEY`.

From [Record demo video](17-demo-video.md): README run section mentions optional `POLL_SECONDS` (default 30). Evals are now 67 cases (Leak 15, incl. l15 diets-in-group), all 100% at 3dcaf88: update counts. WRITEUP privacy paragraph: Dietary needs are gathered 1:1 (the invite asks; only the Host sees them). In the group, Butler says it isn't allowed to share them and defers to the Host, rather than claiming not to know.

From [Arcade feature proposal](15-feature-proposal.md): paste its "WRITEUP text (final)" as the WRITEUP section "Feature proposal for Arcade", unchanged (ends at "Why only Arcade can build it"), and link it from the top of README. Re-check the call counts if `POLL_SECONDS` default changes.

## Answer

**Written** (commit fc13d25 in `projects/gettogether/`): `README.md`, `WRITEUP.md`, `docs/architecture.md`. 121 deterministic tests still green.

- **README:** what Butler does (5 steps), links up top (video, WRITEUP, Feature proposal for Arcade, architecture), prerequisites, setup, run, try-it email, tests + evals, layout, external resources + AI use.
  - Reviewer setup: fresh Gmail for Butler; Arcade account signed up with that address (or Butler added as a project member) → API key; `.env`; `uv run scripts/authorize.py`, link opened in a browser signed in to Arcade as Butler. Catalog scopes only. No timezone step. Host + ≥1 Guest any provider (test accounts).
  - Run: `uv run butler`, `--once`, `POLL_SECONDS` (default 30). Notes: only email after first start, one Dinner, reset = delete `butler.db` + the event; "unknown sender" invites; Reply all in the group.
  - Evals: `uv run pytest` (121, no keys, CI) vs `uv run pytest evals` (Anthropic key only, ~1.5 min, 67 cases), `--runs 1` / `--case` / `--workers`, RESULTS.md link.
  - AI use: Claude Code for planning (Matt Pocock's skills: wayfinder, grilling, domain-modeling, research, prototype; glossary), research + live spikes, code one build step at a time, wording review. "Planning notes and Claude Code threads available on request" (user to confirm).
- **WRITEUP** (~1,670 words incl. the proposal): hybrid loop vs workflow (D2, D8); privacy by construction (D3, D4, D9, D15, diets-in-group paragraph); Butler's own account (D1); calendar decides (D13); exactly once (D5); catalog only + reply-all group + subject tradeoff + first names (D6, D10); evals paragraph from 07 + results + the by-construction caveat (D11, D12); left out (D7, D14 one-liner, the 2026-10-06 cuts, fast follows); production (DMARC, `ReplyInThread` relay, push, service + Postgres, evals per prompt change); Feature proposal for Arcade pasted unchanged from 15 (verified byte-identical).
- **docs/architecture.md:** as built. Dropped the design-review table and build-order chart (private process). Fixed: `ask_cancel_confirmation` in toolsets + cancel sequence, `record_rsvp` arg names + group variant, gateway signatures, 120s poll overlap, Group-thread-to-Butler-only = private, Change notices to every Guest outside the group, data model fields (host_name, cancel_asked_in, guest name, outbox message_id, message sender/skipped, change kinds, gate traces), delete verified. `pstack/docs/architecture.md` left as the pre-build version.

Open for the user: the "available on request" line in README; WRITEUP length vs "a few paragraphs" (cut candidates: production list, catalog paragraph). Video link is `TODO(link)` in README → 17/18.

Time: ~5 min wall (14:58–15:03, 2026-10-07), agent-driven.
