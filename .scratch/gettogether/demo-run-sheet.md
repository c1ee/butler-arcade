# Demo run sheet (Record demo video)

Target ≤3:00. Loom free (5 min cap, 720p): **pause** after each send, **resume** when the terminal shows the "wait for" line. Voiceover added after; VO column is a gist, not a script.

Dry run 2026-10-06: all steps passed live (step 5 reply since reworded, commit 3dcaf88); Butler answers ~10–15s after a send at `POLL_SECONDS=10`. Log: `spike/demo_dryrun.log`.

## Before recording (once)

- [ ] Clear Butler's emails from Host, A, B Gmail (search `arrialee7` → select all → delete) and C's Outlook. Butler's own inbox needn't be cleared.
- [ ] I've run `rm butler.db` and checked no 10/17 events remain (done after dry run).
- [ ] Fresh Chrome profile, signed in: Host (campingchra), A (augustclee7), B (xhakaout32). Pinned tabs in order: **Host Gmail · A Gmail · B Gmail · C Outlook · Host Calendar (Sat 10/17, day view) · A Calendar**. Bookmarks bar hidden, zoom 125%.
- [ ] Window: browser ~2/3 left, terminal ~1/3 right, terminal font ≥18pt.
- [ ] Terminal: `cd ~/chrislee/projects/gettogether && rm -f butler.db && POLL_SECONDS=10 uv run butler`. Wait for `polling every 10s` before starting Loom.
- [ ] Loom: screen only (or with camera bubble, your call), full screen.

## Steps

Gmail rules on screen: in the Group thread ("Everyone coming: …") use **Reply all**. In the Host thread ("Dinner Saturday") use plain **Reply**.

| # | Tab | Do (exact text) | Pause → resume when terminal shows | Show after resume | VO gist |
|---|---|---|---|---|---|
| 0 | Host Gmail | (Loom start) | – | empty inbox + terminal "polling every 10s" | GetTogether: Butler is an email assistant that runs a dinner for the Host. Guests just use email and their calendar. |
| 1a | Host Gmail | Compose to `arrialee7@gmail.com`, subject `Dinner Saturday`: `Hi Butler! I'm hosting dinner at my place Saturday 10/17 at 7pm: 412 Alder St, Oakland. Please invite augustclee7@gmail.com, xhakaout32@gmail.com and guest.c.gettogether@outlook.com. Street parking only, let guests know.` | `replied to campingchra… (… draft_shown)` | Butler's reply: draft + invite preview, parking marked shareable | Host writes in plain English; Butler drafts and shows exactly what guests will get. Nothing goes out until the Host approves, and code enforces that, not the prompt. |
| 1b | Host Gmail | Reply: `Looks good, send it!` | `sent invite to guest.c…` | Host Calendar: event 7pm, Host only; A Gmail: private invite | Approve → event on the Host's calendar, one private invite per guest. Nobody sees who else is invited. |
| 2 | A Gmail | Open invite → Reply: `Yes! I'm bringing my partner, she's vegetarian. What's parking like?` | `sent reply to augustclee7…` | A: reply answers parking from the Host's note. Host Gmail: notice "is coming! Bringing: 1 more · Dietary needs · Headcount is now 2" | One messy email: RSVP, a plus-one, a dietary need, a question. Butler records all of it, answers from the Host's note, and the dietary need goes only to the Host. |
| 3 | B Gmail | Open invite → Reply: `Yes, count me in!` | `sent group_start…` then `sent reply to xhakaout32…` | B: "Everyone coming: …" opener (Coming: 3) | Two yeses → Butler starts one group thread with the Host and everyone coming. |
| 4 | B Gmail | In "Everyone coming", **Reply all**: `Can't wait to see everyone!` | `silent in the Group thread: …` | point at the terminal line | Chatter → Butler stays quiet. A small model call decides when it should speak. |
| 5 | B Gmail | **Reply all**: `Butler, any dietary restrictions I should know about? I'm bringing dessert.` | `sent reply to xhakaout32…` | Butler's group reply: "not allowed to share in the group, please let [Host] answer" | A's diet went to the Host privately. In the group, Butler's tools can't even read it, so it can't leak, by construction. |
| 6 | Host Gmail | In "Dinner Saturday", **Reply**: `Can we move it to 8pm?` | `sent change_notice to guest.c…` then `sent reply to campingchra…` | Host Calendar: 8pm. B Gmail: group post "8 PM (was 7 PM)". C Outlook: private update | One Host change: calendar updated silently, one group post, a private note to C, who hasn't answered. Each person hears once. |
| 7 | C Outlook | Open the update → **Reply**: `Count me in!` | `sent welcome to group` | C Outlook: group welcome. Host Calendar: C on the guest list | Outlook guest, same flow: on the calendar and welcomed into the group with the current details. |
| 8a | Host Gmail | In "Dinner Saturday", **Reply**: `Please cancel the dinner.` | `… now confirming_cancel)` | Butler asks to confirm, lists who'll be told | Canceling takes a confirmation, and code enforces that too. |
| 8b | Host Gmail | **Reply**: `Yes, cancel it.` | `sent cancel_notice to group` | A Gmail: cancel post. Host Calendar + A Calendar: event gone | One cancel note each; the event disappears from every calendar without Google's own email. |
| 9 | (last frame) | (Loom stop) | – | – | Not shown: Butler asks for missing details; RSVP buttons on the calendar invite count silently; guests can change their mind; evals: 67 cases × 3 runs, all passing, zero leaks. |

## If a take fails

Stop Butler (Ctrl-C), I silently delete the event (`demo.py cleanup`) and `rm butler.db`, you clear the 4 inboxes, restart Butler.
