# Live check against real Gmail + Calendar

Type: task
Mode: AFK
Status: resolved
Blocked by: 01, 04

## Question

Using throwaway scripts in `.scratch/gettogether/spike/`, authorize Butler via Arcade (user_id = Butler's email) and confirm against real accounts whatever the capabilities research flagged as live-only. At minimum:
- Create event on Butler's calendar with Host as attendee; add Guest A later. Does A receive Google's invite email?
- Update description: do attendees get notified?
- Send a private email to A; A replies; confirm thread_id mapping in Butler's inbox.
- Group email to Host + A + B; then reply-all adding C. Does C receive it in-thread? Quoted history?
- Deliverability: inbox vs spam for each.
Record facts the build depends on.

Start from the 13-item live-check list in the Answer of [Arcade Gmail + Calendar capabilities](01-arcade-gmail-calendar-capabilities.md).
Also from [Custom Arcade MCP tool runtime](03-custom-mcp-tool-runtime.md): does `client.auth.start` return `completed` immediately when scopes are already granted?

## Answer

Fully automated: Butler + host/A/B all authorized in Arcade. Scripts are in `spike/` (`p1_butler` → `observe` → `p2_humans` → `p3_butler` → `observe`), the log is in `spike/log.jsonl`, and the run tag is `rk7`. Gmail 8.12.1, GoogleCalendar 4.2.0.

**Calendar**
- `CreateEvent(send_notifications_to_attendees="all")` **does** email the invite (live tool has the param). `"nobody"` is accepted and silent.
- `UpdateEvent` add attendee + `all` → only the new guest is emailed; existing attendees get nothing.
- Remove attendee + `all` → removed guest gets "Canceled event"; others get nothing.
- Description-only update + `nobody` → silent.
- `UpdateEvent` returns a **string**, not the event. Re-read with `GetEvent`.
- Naive datetimes resolve in Butler's calendar tz: `19:00` → `-07:00 America/Los_Angeles`.
- Every invite is titled **"Invitation from an unknown sender: …"**. Google won't auto-add it to the guest's calendar until they interact.
- RSVP channel works: `GetEvent` attendees carry `response_status` (accepted/declined/needsAction) and `additional_guests` (calendar "+N" could feed Plus-ones).
- Guest RSVP (API `RespondToEvent`, standing in for clicking Yes/No) → "Accepted:/Declined: <title>…" mail **from the guest's address** lands in Butler's inbox, each in its own thread. The router must recognise these (subject prefix) and not treat them as conversation.

**Gmail**
- `SendEmail` returns `{id, thread_id, label_ids, url}`. A guest's reply lands in Butler's mailbox with the **same thread_id** → thread mapping works.
- `ReplyToEmail(every_recipient, cc=[B])` on **Butler's own** message: To keeps the original recipients (host); it isn't emptied. Cc = A + B. Host, A, and B each see one thread; B's starts at the join point with the quoted last message.
- `ReplyToEmail(only_the_sender, cc=[A,B])` on the host's message: To = host, Cc = A, B, and it stays in the same thread for everyone → the D6 upgrade (Butler controls who receives its group posts) works.
- Quotes the original ("On … wrote:" + `>`). Subject stays a single "Re: X" across replies.
- **Comma-separated `recipient` is broken:** headers look right, but the host got it in **Spam** and A **never received it**. Use `recipient` + `cc`.
- A guest replying to a calendar invite email reaches Butler (Reply-To = Butler) but as a **new thread** in Butler's mailbox (Butler has no copy of the invite). Route it by sender + event title in the subject.
- Polling: `after:<epoch>` passes through. `in:inbox` excludes Butler's own sent mail (`-from:me` is redundant). `date` is a string like `"Tuesday, October 06, 2026 at 05:42:16 UTC"` → dedupe by message id rather than relying on the date. `include_spam_trash` param exists.
- Deliverability from the fresh account: everything landed in Primary inbox except the broken comma-recipient mail (Spam).
- From display name is the Google account name ("Arri Lee"). Rename it to "Butler" before the demo.

**Auth**
- One union-scope consent covers all tools. `ReplyToEmail`'s `calendar.settings.readonly` triggers no extra prompt.
- `auth.start` with a subset of granted scopes returns `completed` + token immediately.

**Non-Gmail guest (C, Outlook.com; observed by hand, run tag `ck9`, script `p4_outlook.py`)**
- cc-added mid-thread → Outlook groups Butler + host + Butler (only_the_sender+cc) into **one conversation**, with the quoted earlier text shown.
- Everything (group mail, private mail, calendar invite) landed in **Focused**, not Junk.
- C's reply to a private email → same thread_id in Butler's mailbox.
- Outlook "Accept" on a Google invite → "Accepted: <title>" mail from C in Butler's inbox, and `GetEvent` shows `accepted`.
- Outlook quotes differently: `________________________________\nFrom: … Sent: …`, not Gmail's "On … wrote:". Anything that strips quoted history before the model sees it must handle both.
- Butler's display name is now "Butler GetTogether" (renamed).

**Not separately verified:** a human clicking Yes in the Gmail UI vs the API RSVP (same Calendar mechanism; Outlook's human click did work).

Time: ~25 min automated run (22:18–22:43) + ~15 min Outlook round (23:00–23:15), excluding OAuth setup (ticket 04).
