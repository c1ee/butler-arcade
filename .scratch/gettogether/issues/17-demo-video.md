# Record demo video

Type: task
Mode: HITL
Status: resolved
Assignee: chrislee (session 2026-10-06, demo)
Blocked by: 08, 13

## Question

Record the 2–3 min demo following PLAN.md's demo script with the demo accounts. Agent prepares the run sheet and resets state between takes; user records.

From [Build Group thread](12-build-group-thread.md): in the Group thread, Gmail's plain Reply reaches only Butler and is handled as private; use Reply all for group posts on screen.

From [Build Host writes](13-build-host-writes.md): demo step 10's "event gone from calendars" holds: a `nobody` delete removes it from attendees' calendars with no Google email. Cancel takes two Host emails (ask, then "yes"). After a time change, thread subjects still show the old time.

From [Email wording review](08-email-wording-review.md): before recording, rename the demo accounts' Google display names (Host campingchra shows as "Camping" in every email; xhakaout32 as "Sang Lee"); start a new Dinner after renaming. Subjects now carry only the date, so a time change no longer leaves them stale.

Graduated from the map's fog (build done): **recording logistics** still to settle with the user: which accounts are on screen, showing inbox + calendar together, cut points, whether to shorten the poll interval for recording.

From [README + WRITEUP](16-readme-writeup.md): put the Loom link in README's `TODO(link)` (top bullets).

## Progress (2026-10-06)

Recording logistics settled with the user. The run sheet is [demo-run-sheet.md](../demo-run-sheet.md):
- Loom free (5 min cap, 720p): pause while Butler works, so each pause is the cut. One take; voiceover added after. Spoken intro (~5s); outro is voiceover over the last frame.
- Layout: browser ~2/3 (one fresh Chrome profile, pinned Host · A · B · C Outlook · Host Calendar · A Calendar tabs) + Butler terminal ~1/3. Calendar shown = Host's.
- Hard 3 min. Steps cut to 9: setup includes the parking note (no "asks for missing place"); no private Host note, since "surprise for B" was incoherent with two-audience notes. The privacy beat is now B asking about diets in the group. C (Outlook) says yes after the 8pm notice; calendar-No goes to the outro; cancel is the ending (moves to the outro too if long).
- `POLL_SECONDS` env var added (default 30), recorded at 10. In the group, Butler now defers diet questions ("not allowed to share such details in the group, let [Host] answer"; Host asking in the group → ask privately). New Leak case l15. Commits 3dcaf88 + d0a8dfc (evals 67 cases, all 100%, 0 violations).
- Dry run: all 9 steps passed live (log `spike/demo_dryrun.log`, driver `spike/demo.py`). Replies land ~10–15s after a send. Display names renamed by the user. Reset done (db deleted, no 10/17 events).

Remaining: user clears the 4 inboxes, records + voices over, uploads to Loom; link → this ticket's Answer.

## Answer

Recorded: https://www.youtube.com/watch?v=bafARB1hod8 (in README, commit 2d0e1fa). **Currently Private** (checked 2026-10-07: "Private video", login required). Must be Unlisted/Public before submitting → Submit.

- Recorded by the user with the run sheet's 9 steps against their own Butler run (4 test Dinners, all canceled; no leftover events on Butler's or the Host's calendar). Voiceover added after, outside Loom (Loom can't add narration to an existing recording).
- Build changes from this ticket: `POLL_SECONDS` env var (3dcaf88); group diet questions deferred to the Host, plus Leak case l15 (3dcaf88, evals d0a8dfc: 67 cases, all 100%).
- Live-run observations: Arcade outage 10:58–11:04 on 2026-10-07 ("This tool or version is not available on this worker" on SearchEmailsByQuery/GetEvent) plus one request timeout. The poll loop retried and recovered with no lost email. WRITEUP material for polling/reliability if wanted.

Time: agent ~1h (logistics grilling, poll setting + prompt fix + evals, run sheet, dry run 21:12–21:21). User's recording + voiceover not tracked.
