# GetTogether: decisions and tradeoffs

Butler runs a dinner over email: setup with the Host, private invites, RSVPs, a group thread, changes and cancel. The decisions below are the ones that shaped it. D-numbers point to the [architecture doc](docs/architecture.md#9-decision-index), which has the diagrams.

## Hybrid: a tool loop for conversation, a workflow for everything else (D2, D8)

Code decides who Butler is talking to, what it may see, who receives each email, and how effects reach Gmail and Calendar. Claude decides what to read and which domain action to take. I considered one structured call with the context preloaded, which is enough for Q&A on state this small. I chose a loop because emails are compound: "yes! bringing my partner, she's vegetarian. what's parking like?" is an RSVP, a Plus-one, a Dietary need and a question at once. The loop costs latency and varies run to run, so it's capped at 6 steps (the last one must answer) and every step is traced.

Invites, change notices, the draft preview and the calendar description are templates, because they have to be predictable and testable. Claude writes only replies. In the Group thread a cheap structured `should_speak` call runs first, so Butler stays out of chatter.

## Privacy by construction, not by prompt (D3, D4, D9, D15)

Butler holds private data (Dietary needs, private Host notes, who declined) and writes into threads several people read. The rule: what Butler may reveal = the smaller of what the asker and the audience may see. The Host asking "any allergies?" in the Group thread gets the Guest-level answer, because Guests read the reply.

That rule is enforced by which tools exist, not by instructions. Each email gets a toolset picked by sender role × thread × Dinner state. No tool a Guest or the group can call returns private data. `record_rsvp` has no guest parameter: it writes for the sender. `send_invites` exists only after the Host was shown the draft, and `cancel_dinner` only in the Host's next email after Butler asked to confirm. Claude never sees raw Gmail or Calendar tools and never picks recipients.

Context comes from the real Gmail thread, each message labeled by its real sender, with the quote the sender's mail app pasted stripped. A pasted quote is editable, so a forged "On Tue, [Host] wrote: …" would be an injection; the real thread can't be forged and only holds what its readers already got. Dietary needs are gathered one-to-one (the invite asks; only the Host sees them). Asked about them in the group, Butler says it isn't allowed to share them and defers to the Host, rather than claiming not to know.

## Butler is its own Google account (D1)

One Arcade grant, Butler's; Hosts and Guests authorize nothing. Acting on each Host's own account was the alternative, but Arcade's default Google app only completes grants for members of the developer's Arcade project, so real Hosts would need a custom OAuth app and user verifier. Butler owns the Calendar event; the Host is an attendee.

## The calendar decides who's coming (D13)

Guests click Yes/No on calendar invites without telling anyone, so the attendee list is the source of truth, read every poll. Butler can add and remove attendees but can't set a Guest's answer (catalog `RespondToEvent` answers only as Butler). So coming = on the calendar and not declined there: Yes, Maybe, or no answer yet. An email "no" takes a Guest off the calendar; an email "yes" after a calendar No removes and re-adds them with one fresh invite. Calendar answers are silent, since the Host can see the calendar. Rejected: email-only RSVPs (two sources of truth that drift), counting only calendar Yes (Guests would RSVP twice), a custom tool to set answers.

## Every Change reaches everyone exactly once (D5)

One Host email = one Change, however many tool calls it took: the calendar updates silently, the Group thread gets one post, and each Invited or Attending Guest outside it gets one private note. State changes, outbox rows (Butler's reply included) and "message processed" commit in one SQLite transaction; sending happens after, row by row. A crash mid-send resends only unsent rows, and an email is never handled twice.

## Catalog tools only, no custom tool (D6, D10)

A live check before building showed Arcade's catalog (Gmail 8.12.1, Google Calendar 4.2.0) covers every effect Butler needs, including the subtle ones: adding one attendee emails only them, and description updates can be silent. A custom Arcade MCP tool would close two gaps, neither needed for P0:

- **Exact thread recipients.** `ReplyToEmail` takes To from the email it replies to, quotes it, has no Reply-To, and can't set a subject. Butler posts to the group by replying to the newest member's email "to the sender only" with everyone else in Cc. Subjects carry only the date, so a time change can't leave a stale time in every subject line (a date change still would).
- **Sender authentication.** No tool exposes SPF/DKIM/DMARC results, so identity rests on the From address. Forged senders are out of scope for the demo.

The Group thread is plain reply-all. Email can't show history to newcomers, so later yeses get a welcome with the current time, place, Headcount and who's coming. Butler adds people and never removes anyone, so its Cc list never reveals who declined. Guests see each other by first name only.

## Evals: pytest, with privacy checked on both sides (D11, D12)

Evals are plain pytest, not `arcade evals`. The main reason is scope: evals with maximum control first, then decide what to offload to a platform. `arcade evals` also only scores the tool calls in the model's first response. It never runs the loop or reads the reply, which is exactly where an agent like Butler leaks. So the harness drives the real loop against a fake Gmail and Calendar that derive recipients and quote replies the way the real ones do.

Privacy is checked twice. Every Planted secret has an owner, and only the Host and that owner may see it. The input check asserts Claude is never shown a secret its reader may not see. The output check asserts nothing Butler sends (emails, including Gmail's quoted text and derived recipients, and the Calendar event) carries one. Both run on every eval Run and every deterministic test. Leaks are zero-tolerance, and a Butler that refuses everything fails too, because each leak case also requires an allowed fact in the reply.

Results: 67 cases × 3 Runs, Behavior 105/105, Leak 45/45, Speak/silent 51/51, 0 privacy violations ([evals/RESULTS.md](evals/RESULTS.md)). The honest caveat: the Leak evals pass mostly by construction. Guest and group toolsets never return private data, so they mainly guard against made-up answers and prompt drift; the real tests are the Host asking in the group and a Guest's own note in the group. 100% confirms the design rather than stressing it. Next: multi-email conversations, LLM-judged replies, paraphrased attacks.

## What I left out

- **Polling, not push (D7).** Arcade has no inbound trigger, so Butler polls every 30 seconds. That's the feature proposal below.
- **One Dinner at a time (D14).** Every table is keyed by Dinner and every thread maps to one Dinner, so multiple Dinners mostly means routing fresh emails: a new Host thread starts a new draft, and a Guest email that isn't a reply is matched by Dinner title, or Butler asks which one.
- **Cut to stay near the 6-hour guideline**, designed but not built: Escalations (Butler forwards a question it can't answer to the Host and relays the answer), Uninvite (for now Butler tells the Host to tell the Guest directly), a catch-up summary for late joiners, and the calendar's "+N" as Plus-ones (needs a rule for which channel wins). Cancel was kept: a Host must be able to call it off.
- **Fast follows:** nudges to non-responders, a day-of logistics email, a Host-set +1 policy, `arcade evals` for tool-call scoring.

## What changes for production

- **Trust the sender:** check DMARC before acting on an email, since identity binding rests on From.
- **A custom `ReplyInThread(to, cc, reply_to, subject)` tool** to make the Group thread a relay: Reply-To = Butler, and Butler rebroadcasts to current members. Butler then owns membership (late joiners and drop-outs handled properly) and subjects stay current, at the cost of latency and the sender's own From.
- **Push instead of polling**, if Arcade adds inbound triggers.
- **Run as a service:** many Hosts and Dinners, Postgres instead of SQLite, the outbox drained by a worker. The outbox and per-email transaction already have that shape.
- **Live evals on every prompt or model change**, not only on demand.

## Feature proposal for Arcade

### Feature proposal: inbound triggers

**Problem.** Arcade lets an agent act on a user's accounts but not hear from them. An agent that reacts to new email or calendar changes has to poll. Every email assistant, support-triage agent or scheduling agent built on Arcade writes the same loop.

**Evidence from Butler.** Butler polls every 30 seconds: one `Gmail.SearchEmailsByQuery`, plus one `GoogleCalendar.GetEvent` per live Dinner to catch Guests answering the invite. With one Dinner that's 5,760 tool calls a day, almost all of them empty. The free plan's 2,000 calls a month would last about 8 hours. On the Team plan it would cost ~$1,700 a month for an agent that's mostly idle (we had unlimited take-home credits). Polling also costs code: a cursor, a 120-second re-read window because Gmail search indexes some emails late, and a calendar check every cycle. Replies wait up to 30 seconds.

**Why only Arcade can build it.** Gmail push (`users.watch`) publishes to a Pub/Sub topic that must sit in the same Google project as the app making the call. On Arcade's default Google app, that project is Arcade's, so a developer can't set up Gmail push even if they want to. Arcade also already holds the user's token, so it can renew watches (Gmail's must be renewed at least every 7 days) and fetch what changed.
