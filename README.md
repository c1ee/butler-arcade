# GetTogether

People stopped hosting dinner parties because the logistics are tedious: chasing RSVPs, collecting how many people each guest brings and what they can't eat, answering the same questions, keeping everyone updated. **Butler** is an organizer with its own Gmail and Google Calendar that does that work. The Host and the Guests only ever email it; nobody but Butler authorizes anything.

- **Demo video:** https://www.youtube.com/watch?v=bafARB1hod8
- **Decisions and tradeoffs:** [WRITEUP.md](WRITEUP.md)
- **Feature proposal for Arcade (inbound triggers):** [WRITEUP.md → Feature proposal for Arcade](WRITEUP.md#feature-proposal-for-arcade)
- **Architecture** (diagrams, data model, privacy model): [docs/architecture.md](docs/architecture.md)

## What Butler does

1. The Host emails Butler in plain English ("dinner Sat 7pm at mine, invite a@…, b@…"). Butler asks for anything missing, then shows the draft and the exact invite. Nothing goes out until the Host approves.
2. On approval, Butler puts the Dinner on its calendar (the Host is invited) and emails each Guest privately.
3. Guests reply in free text: yes/no, how many they're bringing, Dietary needs, questions. A yes puts them on the Calendar event; Dietary needs go only to the Host. The calendar invite's Yes/No buttons count too.
4. Once two Guests are coming, Butler starts one Group thread with the Host and everyone coming, welcomes later yeses, and stays quiet in it unless it's needed.
5. The Host can change the time or place, add notes (shareable or private), invite more people, ask anything, or cancel. Each Change reaches everyone affected once: the calendar silently, one group post, one private note to each Guest outside the group.

Claude handles the conversation through a small set of domain tools picked per sender and thread. Code decides who Butler is talking to, what it may see, and who receives each email. Details in [WRITEUP.md](WRITEUP.md).

## Prerequisites

- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- An [Anthropic API key](https://console.anthropic.com/)
- A new Gmail account for Butler. Its Google Calendar is the Dinner's calendar.
- An [Arcade](https://arcade.dev) account **signed up with Butler's Gmail address**, and an API key from it. With Arcade's default Google app, consent for a `user_id` only completes in a browser signed in to Arcade as that same address, so Butler's address needs its own Arcade login (signing up with it is simplest; adding it as a member of your Arcade project also works).
- A Host email address and at least one Guest email address that you can read. Any provider works for Guests (tested with Gmail and Outlook.com). Use test accounts: Butler emails whatever addresses the Host gives it.

Optional: rename Butler's Google account to "Butler" (Google Account → Personal info → Name). Every email and invite shows that name.

## Setup

```sh
git clone <this repo's URL> gettogether && cd gettogether
uv sync
cp .env.example .env   # then fill in ARCADE_API_KEY, ANTHROPIC_API_KEY, BUTLER_USER_ID, HOST_EMAIL
uv run scripts/authorize.py
```

`BUTLER_USER_ID` is Butler's Gmail address. `HOST_EMAIL` is the one address Butler treats as the Host.

`authorize.py` grants Butler's Gmail and Calendar to Arcade once (catalog scopes only, no custom tools to deploy). It prints a link and waits. Open the link **in a browser signed in to Arcade as Butler's account**, then sign in to Google as Butler and allow access. In a browser signed in to a different Arcade account, the grant silently stays pending. Run it again any time; it prints "already authorized" if the grant exists.

There's no timezone step: Dinner times are read and written as America/Los_Angeles (`butler/config.py`), with explicit offsets.

## Run

```sh
uv run butler          # poll Butler's inbox every 30s until Ctrl-C
uv run butler --once   # poll once and exit
POLL_SECONDS=10 uv run butler   # optional: poll faster (default 30; also settable in .env)
```

Butler logs every email it sees, where it routed it (Dinner, thread, sender's role) or why it skipped it, and every email and calendar write it sends.

**Try it.** From the Host address, email Butler:

> Hi Butler! I'm hosting dinner at my place Saturday 10/17 at 7pm: 412 Alder St, Oakland. Please invite guest1@example.com and guest2@example.com. Street parking only, let guests know.

Reply "looks good, send it" to the draft, then answer the invites from the Guest accounts. Reply to Butler from the Guests' inboxes; in the Group thread ("Everyone coming: …"), use **Reply all**: a plain Reply reaches only Butler and is answered privately.

Notes:
- Butler only handles email that arrives after its first start, and one Dinner at a time. To start over, stop Butler and delete `butler.db` (the Calendar event stays; delete it in Butler's calendar).
- Google titles Butler's calendar invites "Invitation from an unknown sender" and doesn't put them on the Guest's calendar until the Guest answers. That's expected.
- A reply takes up to one poll interval plus ~10s.

## Tests and evals

```sh
uv run pytest         # 121 deterministic tests, no keys, under a second. CI runs these on every push.
uv run pytest evals   # live evals against Claude: needs only ANTHROPIC_API_KEY, ~1.5 min
```

The deterministic tests run Butler against a fake Gmail and Calendar (which derive recipients and quote replies like the real ones) with scripted Claude responses.

The live evals drive the real tool loop against the same fakes: 67 Eval cases × 3 Runs, in three families: Behavior (graded by outcome: state changes, emails sent, facts in the reply), Leak (zero tolerance), and Speak/silent (does Butler reply in the Group thread at all). A privacy check runs on every test and every Run: no private fact may be shown to Claude, or sent to anyone, outside the people allowed to see it. Latest results: [evals/RESULTS.md](evals/RESULTS.md) (all 100%, 0 privacy violations). Options: `--runs 1`, `--case <id substring>` (repeatable; filtered runs don't rewrite RESULTS.md), `--workers N`. Each Run's trace goes to `evals/traces/` (gitignored).

## Layout

```
butler/
  main.py      poll loop: route each new email, handle it once, then tick (calendar sync, close past Dinners)
  router.py    email → (Dinner, thread, role), from thread id and sender only
  agent.py     the tool loop: thread history, scoped tools, 6-step cap, traces
  tools.py     domain tools and which exist for each (role, thread, Dinner state)
  gate.py      should_speak: one structured call, reply in the Group thread or stay silent
  sync.py      per-poll Calendar read: Guests' Yes/No answers
  effects.py   a Change → outbox rows → Gmail/Calendar, exactly once
  render.py    templates: invites, notices, draft preview, Calendar description
  store.py     SQLite (butler.db)
  gateway.py   the only module that calls Arcade
  config.py    settings from .env
scripts/authorize.py   one-time Google consent for Butler through Arcade
tests/         deterministic tests + fakes + privacy checks
evals/         live evals, cases, harness, RESULTS.md
docs/architecture.md
```

## External resources and how I used AI

**Runtime**
- [Arcade](https://arcade.dev) (`arcadepy`): OAuth for Butler's Google account and every Gmail/Calendar call, through catalog tools (Gmail 8.12.1, GoogleCalendar 4.2.0). No custom tools.
- Anthropic API (`anthropic` SDK), model `claude-sonnet-5-5` (set `MODEL` to change): the tool loop and the should_speak gate.
- `pydantic` (tool arguments, structured output), stdlib `sqlite3`, `pytest`, `uv`, GitHub Actions.

**Docs read:** Arcade docs (Gmail and Google Calendar toolkit references, `arcade evals`, Contextual Access, pricing), the `arcade-mcp` source, Gmail API (threads, search filtering, `users.watch`), Google Calendar API (`events.insert`/`update`).

**Coding agent: Claude Code** was used throughout, as planner and pair:
- Planning: the problem, user stories, P0 vs fast-follow scope, and every decision in the WRITEUP were worked out in Claude Code sessions that grilled me on user stories and edge cases. The effort was run as a map of decision tickets (spike → live checks → decisions → build → evals → docs), using [Matt Pocock's agent skills](https://github.com/mattpocock/skills) (wayfinder, grilling, domain-modeling, research, prototype). A glossary kept terms consistent between code, prompts and docs.
- Research: Claude Code subagents read Arcade's and Google's docs, and ran live spike scripts against the real Gmail/Calendar tools to check behavior before building on it (e.g. which calendar updates email attendees, how replies thread, what reaches Outlook).
- Code: written with Claude Code from those decisions, one build step at a time, each run live against real accounts before the next.
- Wording: every email Butler sends went through a line-by-line review with me before the demo.

The planning notes and Claude Code threads are available on request.
