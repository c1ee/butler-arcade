# Email wording review

Type: task
Mode: HITL
Status: resolved
Assignee: chrislee (session 2026-10-06)
Blocked by: 13

## Question

Review Butler's system emails in one pass before recording (scope cut 2026-10-06: wording is written during the build, not prototyped first). Templates in `render.py`: Host draft preview (H1), Guest invite (H2, incl. default +1 line and "to change your RSVP, just reply to this email"), Group thread opener and late-joiner welcome with current facts (H3), Change notice (H4), decline thank-you (G3), cancel message (H8), calendar description. User reacts; agent applies edits.

From [Build tool loop + Host setup](10-build-tool-loop-setup.md): live samples in the tl1 run (Host and Guest inboxes). Known nit: Claude repeats "reply 'send it'" above the preview's own approve line despite the prompt. Title is "Dinner with <Host first name>" from the Host's Gmail display name.

From [Build Guest flow](11-build-guest-flow.md): new samples in run gf1 (Host + A + B inboxes): Host notice (`render.host_notice`), description "Coming: 3 (August, Sang Lee + 1 more)", Guest replies. The decline thank-you is Claude's reply (prompt `agent.GUEST`), not a template. Nits: Q&A replies restate dinner facts and say "the Host" despite the prompt.

From [Build Group thread](12-build-group-thread.md): new templates `render.group_opener` and `render.welcome`; samples in run g12 (Host, A, B inboxes). Group replies are Claude's (`agent.GROUP`). Welcome uses Gmail display names ("Welcome, Sang Lee!").

From [Build Host writes](13-build-host-writes.md): new templates `render.change_notice` (group / invited / attending), `render.change_attachment` (update attached to Butler's group reply), `render.cancel_notice`; samples in run hw1 (Host, A, B inboxes; C's in Butler's sent). Known: subjects keep the old time after a Change (`ReplyToEmail` can't set a subject); Host replies recap the dinner and Claude repeated "the calendar invite is updated" above the attached update (prompt lines added, not re-verified live). The `HOST` prompt is `agent.HOST` + `CANCEL_ASKED`; `GROUP_HOST` for the Host in the group.

## Answer

Done. Commit a49f050 on `main` (no co-author line). `uv run pytest`: 105 green on the committed tree, 121 with ticket 14's uncommitted work (only ticket 08's hunks staged). Before/after renders: [wording-before.txt](../wording-before.txt), [wording-after.txt](../wording-after.txt) (`spike/render_all.py`). The user approved all 10 proposed edits.

**Templates (`render.py`):**
- Subjects carry the date, not the time (`render.short_date`): `You're invited: Dinner with Chris, Sat Oct 24`. A reply can't change its subject, so a new time no longer leaves it stale (a new date still does: WRITEUP).
- Group subject `Everyone coming: Dinner with Chris, Sat Oct 24` (was `Group thread: …`).
- Invite: `render.ASK` = "Can you make it? Reply with yes or no. If yes, I'll add you to the calendar invite." (also the Invited change-notice tail; sets up Google's "unknown sender" invite); last line "Questions, or plans change? Just reply to this email."
- Opener: "Here's one thread for <Host> and everyone coming. Reply all to reach everyone." (dropped "Enough of you said yes"). Welcome adds "Reply all to reach everyone." (late joiners never see the opener).
- `render.guest_label` = first name of the display name, else address: Coming lists, welcome, gate/group-post labels, public facts. Host notice keeps full name + address.

**Prompts (`agent.py`):** `BUTLER`: write "guests" in lowercase, never "the Host" ("you" to the Host, the name to others). `SETUP`: never say how to approve or mention "send it"; the attached draft ends with that line.

**Replay (`spike/wording_replay.py`, real Claude + fake Gmail, 4 cases × 3):** 12/12 clean. Setup lead-in has no "send it"; Guest Q&A says "Chris", not "the Host"; Host's group move → "Done, I've moved dinner to 8:30 PM. Everyone will get the update." (no repeated calendar line: ticket 13's leftover verified); Host-thread change reply 2–3 sentences (recap leftover verified). Only "flags" were sentence-initial "Guests will see it".

**User to do before the demo (HITL, ticket 17):** rename the Google display names. Host campingchra shows as "Camping" in every email ("Dinner with Camping"); xhakaout32 shows as "Sang Lee". Butler reads names from the From header, so a new Dinner picks them up.

Time: ~20 min (16:35–16:55).
