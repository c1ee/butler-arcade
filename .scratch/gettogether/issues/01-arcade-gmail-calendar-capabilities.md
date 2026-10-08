# Arcade Gmail + Calendar capabilities

Type: research
Mode: AFK
Status: resolved

## Question

What can Arcade's catalog Gmail and Google Calendar tools actually do, per docs and toolkit source? Answer each with evidence (doc link or source file + line):
1. `GoogleCalendar.CreateEvent` / `UpdateEvent`: can they add/remove attendees on an existing event? Do they send Google's invite email (`sendUpdates`)? Exact param names.
2. Does updating an event's description notify attendees?
3. `Gmail.ReplyToEmail`: reply-all supported? Can it add new recipients (to/cc) in the same thread? Exact params.
4. `Gmail.SendEmail`: does the response include `thread_id` and `message_id`? Is `reply_to` supported?
5. Polling: can `SearchEmailsByQuery` / `ListEmails` filter by time (`after:` epoch) and return message id, thread id, From, date, body? Does the automated-sender exclusion drop anything we need?
6. `Gmail.GetEmail`: are raw headers (Message-ID, Authentication-Results) returned?
Flag anything only a live call can settle; that goes to the live check.

## Answer

Versions: live catalog Gmail 8.12.1 / GoogleCalendar 4.2.0 (authoritative). docs.arcade.dev is stale (8.9.1 / 3.7.1). The only readable source is PyPI 4.2.0 / 3.3.2 (proprietary; there's no public GitHub repo).

1. Yes. `UpdateEvent.attendee_emails_to_add` / `attendee_emails_to_remove` + `send_notifications_to_attendees` ∈ `nobody|all|externalOnly` (live enum is **`nobody`**, not docs' `none`), default `all` → Google `sendUpdates`. It's one switch per call. In 3.3.2 source, CreateEvent drops `sendUpdates` on insert, so it may send no invite (live check).
2. Yes, under the default `all` (Google: "description changes"). Re-renders must pass `send_notifications_to_attendees="nobody"`, and attendee changes should be split from description changes.
3. Reply-all yes: `reply_to_whom="every_recipient"` (default `only_the_sender`; always pass it). New recipients only via `cc` (and `bcc`); there's no `to` param. Same thread via threadId + In-Reply-To/References + "Re:" subject. The reply quotes the original body.
4. Partial. Output `{id, thread_id, label_ids, url}`: `id` = Gmail message id; RFC Message-ID only via GetEmail `header_message_id`. No `reply_to`, thread, or custom-header param in any Gmail tool. `recipient` is a single string; use `cc` for more people.
5. Yes, via `SearchEmailsByQuery(query, result_detail="full"|"lightweight", max_results≤10|50, page_token)`. It's a raw Gmail query (`after:<epoch>` per Gmail docs; tool pass-through needs a live check) with no automated filter. It returns `message_id`, `thread_id`, `sender`, `date`, and `body` (full mode only). `ListEmails` has no time filter, and its default `exclude_automated=True` drops Updates/Forums category mail, so don't poll with it.
6. Partial. GetEmail returns `header_message_id` + `references` (no `in_reply_to`). There's no raw header map and no Authentication-Results.

Live-check needed (→ 05): CreateEvent emails the attendee?; `nobody` accepted; add-attendee+`all` emails new guest only or all guests?; remove+`all` sends cancellation?; description-only+`nobody` silent?; ReplyToEmail cc-add threads for everyone (incl. non-Gmail client); ReplyToEmail on Butler's own msg (empty To); quoting / "Re: Re:" in 8.12.1; `after:<epoch>` pass-through + `date` format; SendEmail comma-separated `recipient`; deliverability/spam placement of mail + invites from fresh account; "Accepted:/Declined:" calendar mails + replies to invite email landing in Butler inbox; ReplyToEmail's extra `calendar.settings.readonly` scope prompt.

Research: [research/arcade-gmail-calendar-capabilities.md](../research/arcade-gmail-calendar-capabilities.md)

Time: ~7 min (13:47–13:54).
