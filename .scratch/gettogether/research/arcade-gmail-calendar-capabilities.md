# Arcade Gmail + Google Calendar capabilities (ticket 01)

Researched 2026-10-05. Answers the six questions in `issues/01-arcade-gmail-calendar-capabilities.md` for Butler (PLAN.md).

## Sources and how much to trust each

| # | Source | Version | Notes |
|---|---|---|---|
| S1 | **Live public tool catalog** (anonymous): `https://experience.arcade.dev/api/public/tools?toolkit=Gmail&limit=100` and `...?toolkit=GoogleCalendar&limit=100` | **Gmail 8.12.1, GoogleCalendar 4.2.0** | What the hosted engine runs today. Full input params and enums, plus output `value_schema`. **This is authoritative for signatures.** The docs generator reads the same endpoint (`docs/toolkit-docs-generator/README.md`, "Data sources"). |
| S2 | docs.arcade.dev reference pages: https://docs.arcade.dev/en/resources/integrations/productivity/gmail , https://docs.arcade.dev/en/resources/integrations/productivity/google-calendar . Backing data: github.com/ArcadeAI/docs `toolkit-docs-generator/data/toolkits/gmail.json`, `googlecalendar.json` (commit a6b3f85, 2026-10-02) | Gmail 8.9.1, Calendar 3.7.1 | **Stale** compared with S1. Example: Calendar enum value is `none` here but `nobody` live. |
| S3 | Toolkit **source**: PyPI wheels `arcade_gmail-4.2.0` (2026-02-23) and `arcade_google_calendar-3.3.2` (2026-02-26). License: "Proprietary - Arcade Software License Agreement" | Gmail 4.2.0, Calendar 3.3.2 | **No public GitHub source exists.** `ArcadeAI/arcade-ai` now redirects to `ArcadeAI/arcade-mcp`, which has no toolkits, and no ArcadeAI org repo contains them. The PyPI wheels are the newest readable code, but they are **4 major versions (Gmail) and 1 major version (Calendar) behind live**. I use them only to show *how* params map to Google API calls, and flag anything that may have changed since. |
| S4 | Google API docs: Calendar [events.update](https://developers.google.com/workspace/calendar/api/v3/reference/events/update), [events.insert](https://developers.google.com/workspace/calendar/api/v3/reference/events/insert); Gmail [filtering guide](https://developers.google.com/workspace/gmail/api/guides/filtering), [threads guide](https://developers.google.com/workspace/gmail/api/guides/threads) | — | Upstream semantics. |

To re-pull S1:
`curl -s "https://experience.arcade.dev/api/public/tools?toolkit=GoogleCalendar&limit=100" | jq '.items[] | select(.name=="UpdateEvent")'`

Source paths below are relative to the unpacked wheels: `arcade_google_calendar/...` and `arcade_gmail/...`.

---

## Q1. `CreateEvent` / `UpdateEvent`: add or remove attendees? Does Google send its invite email (`sendUpdates`)? Exact params

**Answer: yes to add/remove, through `UpdateEvent`. Notification is a single per-call switch. Exact enum values changed in the live version.**

Live S1, `GoogleCalendar.UpdateEvent@4.2.0` params:
- `event_id` (required), `calendar_id` (default `primary`; new since 3.x)
- `attendee_emails_to_add: list[str]`, `attendee_emails_to_remove: list[str]`
- `send_notifications_to_attendees`, enum **`["nobody", "all", "externalOnly"]`**, "Which guests Google emails about the update… **Defaults to all.**"
- `updated_start_datetime`, `updated_end_datetime`, `updated_summary`, `updated_description`, `updated_location`, `updated_visibility`, `updated_recurrence`, `updated_google_meet` (`add`/`remove`), `updated_calendar_id` (live description: "moves" the event to another calendar)
- Output: a **string** ("Event with ID … successfully updated at … View updated event at …"). No event JSON. Use `GetEvent` to read state.

Live S1, `GoogleCalendar.CreateEvent@4.2.0` params: `summary`, `start_datetime`, `end_datetime` (required), `calendar_id` (default `primary`), `description`, `location`, `visibility`, `attendee_emails: list[str]`, `send_notifications_to_attendees` (enum `["nobody","all","externalOnly"]`, "Which guests Google emails an invitation to… Defaults to all."), `add_google_meet`, `recurrence`. Output: `{"event": <raw Google event>}`, which includes `id`.

New live tool: `GoogleCalendar.GetEvent@4.2.0` (`event_id`, `calendar_id`). It returns `attendees[]` with `email`, `response_status`, `additional_guests`, `comment`, plus `description`, `start`, `end`, `location`, and so on. This is useful for reconciling attendees and for spotting guests who RSVP'd with the Calendar buttons instead of by email.

**Enum change:** the docs (S2, `googlecalendar.json` lines 104–112, 851–860) and the 3.3.2 source (`arcade_google_calendar/enums.py`, `SendUpdatesOptions.NONE = "none"`) both use **`none`**. Live 4.2.0 uses **`nobody`**. `DeleteEvent.send_updates` live is also `["nobody","all","externalOnly"]`. Code must send `nobody`. The tool presumably maps it to Google's `sendUpdates=none`, but that mapping is not visible in any readable source.

How the source maps these to Google (S3, Calendar 3.3.2, `arcade_google_calendar/tools/calendar.py`):
- `UpdateEvent` (L301–455) works like this: `events().get(calendarId="primary")` (L356), merge fields (L382–412), filter `attendees` for removals (L414–420), append new `{"email": …}` entries for adds while skipping case-insensitive dupes (L422–431), then `events().update(calendarId="primary", eventId, sendUpdates=<value>, body=event)` (L433–440). So `sendUpdates` **is passed as the Google query param** on update, which is correct. It uses full-replace PUT semantics (S4 events.update: "always updates the entire event resource").
  - 3.3.2 hard-codes `calendarId="primary"` and ignores `updated_calendar_id` apart from stuffing it into the body (L389). Live 4.2.0 adds `calendar_id` and real move semantics. Butler should just use `primary`.
- **`CreateEvent` bug in 3.3.2** (L151–160, L176–179): `sendUpdates` is put **inside the event body dict**, not passed to `events().insert(...)`. Per S4 events.insert, `sendUpdates` is a *query* parameter whose "default is false", so in 3.3.2 **CreateEvent sends no invite emails** whatever the argument says. It is unknown whether 4.2.0 fixed this (the live description now says "Which guests Google emails an invitation to", which hints at a rewrite). → **live check**.

Google semantics (S4 events.update): `sendUpdates`: "'all': Notifications are sent to all guests. 'externalOnly': … non-Google Calendar guests only. 'none': No notifications are sent."

Implications for Butler:
- G1 (yes → attendee + Google invite): `UpdateEvent(event_id, attendee_emails_to_add=[guest], send_notifications_to_attendees="all")`. `externalOnly` is useless for Gmail guests because they *are* Google Calendar users.
- G4 (drop out): `attendee_emails_to_remove=[guest]`. Whether Google emails the removed guest a cancellation under `all` is Google behavior → live check.
- **There is no per-attendee notification control.** One `sendUpdates` applies to the whole PUT. If a call adds a guest *and* changes anything else under `all`, every existing guest may get an "Updated invitation" email. Keep attendee add/remove calls separate from description/time changes.
- H2 (create with host as attendee): if the create-time invite is not sent (the 3.3.2 bug), a workaround is to create without attendees and then `UpdateEvent(attendee_emails_to_add=[host], send_notifications_to_attendees="all")`.
- 3.3.2 passes `updated_start_datetime` through without adjusting the end (L382–388). When moving the time (H4), always send both start and end.
- Full-replace update means GET→PUT. An RSVP click by a guest between the two could, in principle, be overwritten (low risk).

## Q2. Does updating the description notify attendees?

**Answer: only if `send_notifications_to_attendees` is not `nobody`. The default is `all`, so a default call WILL email every guest.**

- Default `all` (S1 UpdateEvent; S3 `calendar.py` L330–333 `= SendUpdatesOptions.ALL`). That value is sent as `sendUpdates` on every update (L438), including description-only ones.
- Google (S4 events.update, deprecated `sendNotifications`): "Whether to send notifications about the event update (**for example, description changes**, etc.). Note that **some emails might still be sent** even if you set the value to false."
- Butler re-renders the description on every change (PLAN "Re-rendered on every change"). That means **every re-render must pass `send_notifications_to_attendees="nobody"`**, or guests get spammed with "Updated invitation" emails. For a real time/place change (H4), `all` may be what you want, since Google's update email doubles as the calendar change notice, but PLAN already emails the group thread.
- Whether Google still sends anything for a description-only change under `nobody` ("some emails might still be sent") → live check.

## Q3. `Gmail.ReplyToEmail`: reply-all? Add new to/cc recipients in the same thread? Exact params

**Answer: reply-all yes. New recipients yes, but only through `cc` (and `bcc`). There is no `to` param. The reply stays in the thread.**

Live S1 `Gmail.ReplyToEmail@8.12.1` params:
- `body` (required, non-empty), `reply_to_message_id` (required; the Gmail API message id, not the RFC Message-ID)
- `reply_to_whom`: enum `["every_recipient", "only_the_sender"]`. **Default `only_the_sender`.** In source the default can be overridden by the server env var `ARCADE_GMAIL_DEFAULT_REPLY_TO` (`arcade_gmail/constants.py` L8–12), so **always pass it explicitly**.
- `cc: list[str]`: "Additional CC recipients. When replying to every recipient, merged with CC from the original message; duplicates are removed (RFC-aware). Duplicates of the reply's To recipients are dropped from Cc… The authenticated user's own email address is removed from Cc on replies."
- `bcc: list[str]` (self removed), `content_type` (`plain`/`html`/`auto`; **default `auto` sends HTML**), `attachments`
- **Scopes:** `gmail.send`, `gmail.readonly`, **`calendar.settings.readonly`**. That last one is unexpected, probably for the user's timezone in the quote attribution. Butler's single OAuth grant has to include it (relevant to ticket 04).
- Output: `{id, thread_id, label_ids, url}`

`cc` **did not exist in 4.2.0**. The S3 4.2.0 signature (`tools/gmail.py` L159–176) has only `body`, `reply_to_message_id`, `reply_to_whom`, `bcc`, `content_type`. Live 8.12.1 has it.

Reply mechanics (S3 4.2.0; may have changed in detail by 8.12.1):
- Recipients (`utils/helpers.py` L135–151): `only_the_sender` → To = original `From`. `every_recipient` → To = original `From` + original `To` (comma-split), with self removed. Cc = original `Cc` (`tools/gmail.py` L195–197). **Original `Reply-To` is ignored.**
- Threading (`helpers.py` L52–62): sets `In-Reply-To` = original Message-ID, `References` = original Message-ID + original References, and the Gmail API `threadId` = original thread. Subject is forced to `"Re: " + original subject` (`tools/gmail.py` L201). This meets Gmail's three requirements (S4 threads guide: threadId, RFC 2822 References/In-Reply-To, matching Subject), so **the reply lands in the same thread in Butler's mailbox**.
- **Quoted history:** the body gets the original message appended as `> ` quoted text with an "On <date>, <sender> wrote:" line (`helpers.py` L34–35, L67–72). Two consequences. (a) A late joiner added via `cc` sees the quoted *last* message, which is group-scope text, so that's fine. (b) Never use ReplyToEmail on a host-private message while cc'ing a guest. It would leak the host's private text. PLAN already never does this.
- 4.2.0 split addresses naively with `split(",")`, which breaks on display names like `"Lee, Chris" <x@y>`. 8.12.1 claims RFC-aware dedupe and adds `email_addresses` parsing, so this is probably fixed.

Implications for Butler:
- H3 late yes: `ReplyToEmail(reply_to_message_id=<latest group msg>, reply_to_whom="every_recipient", cc=[new_guest], body=catch_up)`. This is supported.
- **Possible upgrade to D6:** `reply_to_whom="only_the_sender"` + `cc=[current members minus sender]` gives Butler control over who receives *Butler's own* group messages. Dropped-out guests can be left off Butler's posts, and humans' reply-alls still behave as before. Caveat: if the replied-to message is Butler's own, To becomes empty after self-removal → live check how 8.12.1 handles that. Otherwise reply to the latest *human* message.
- Recipient-side threading for people already in the thread depends on their client honoring In-Reply-To/References + "Re:" subject → live check (e.g. Gmail guest + Outlook/iCloud guest).

## Q4. `Gmail.SendEmail`: does the response include `thread_id` and `message_id`? Is `reply_to` supported?

**Answer: `thread_id` yes. The Gmail message id comes back as `id`. The RFC `Message-ID` header is not returned. Setting a Reply-To header is NOT supported.**

- Live S1 `Gmail.SendEmail@8.12.1` output schema: `id` ("The ID of the sent message"), `thread_id`, `label_ids`, `url`. The same shape is in S3 4.2.0 `tools/gmail.py` L95–101. `id` is the Gmail API message id, which is what `ReplyToEmail.reply_to_message_id` and `GetEmail.email_id` take. To get the RFC `Message-ID` header, call `GetEmail(id)` → `header_message_id`.
- Params: `subject`, `body`, `recipient` (**single string**), `cc: list[str]`, `bcc: list[str]`, `content_type` (default `auto` → HTML), `attachments`. There is **no `reply_to`, no `thread_id`/`in_reply_to`, and no custom headers.** No Gmail tool in the live catalog takes a Reply-To input (checked all 30 tools' params).
  - So the D6 production alternative (relay with group `Reply-To` = Butler) **needs a custom tool**. That doesn't matter for P0.
  - SendEmail always starts a new thread. To post into an existing thread you must use ReplyToEmail.
  - H3 group start: `SendEmail(recipient=host, cc=[confirmed guests])`. In 4.2.0 `recipient` was written raw into the `To` header (`helpers.py` L45), so a comma-separated string probably also works, but that's unverified for 8.12.1. Using `cc` avoids depending on it.

## Q5. Polling: can `SearchEmailsByQuery` / `ListEmails` filter by time (`after:` epoch) and return message id, thread id, From, date, body? Does the automated-sender exclusion drop anything needed?

**Answer: use `SearchEmailsByQuery`. It takes a raw Gmail query (so `after:<epoch>` should pass through) and has no automated filter. `ListEmails` has no time/query filter at all.**

`Gmail.SearchEmailsByQuery@8.12.1` (S1; not in 4.2.0, so no readable source):
- Params: `query` (required, raw Gmail query; description lists `before:/after: YYYY/MM/DD`, `newer_than:`, `-`/NOT, `in:`, `from:`…), `result_detail` (`count_only` / `lightweight` default / `full`), `max_results` (default 10; **cap 50 lightweight, 10 full**), `page_token`, `include_spam_trash` (default false).
- Output per email: **`message_id`**, `thread_id`, **`sender`** (From), `to`, `cc`, `bcc`, `reply_to`, `subject`, `date` (formatted UTC string; in 4.2.0 `format_internal_date` gives "Monday, October 05, 2026 at 20:47:05 UTC", parsed from Gmail `internalDate`), `snippet`, `label_ids`, `header_message_id`, `in_reply_to`, `references`, and `body`/`html_body` **only in `full`**. Also `pagination.next_page_token`, `has_unfetched_emails`, `unfetched_email_ids`.
- **No `exclude_automated` param**, and the description mentions no automatic filtering, unlike ListEmails/ListThreads/ListEmailsByHeader/SearchThreads.
- Field names differ from GetEmail/ListEmails, which use `id` and `from_`. The gateway should normalize them.
- Epoch: Gmail itself supports `after:<epoch seconds>` (S4 filtering guide: "dates … interpreted as midnight … PST… pass the value in seconds instead: `after:1388552400`"). The tool's description only advertises `YYYY/MM/DD`. Whether the tool passes epoch through untouched → live check.
- Suggested poll: `query="in:inbox -from:me after:<last_poll_epoch - 120>"`, `result_detail="full"`, `max_results=10`, paging with `page_token`, deduped by `message_id` (PLAN D5). Or use `lightweight` (50/page) for ids and then `GetEmail` for each new one. The dedupe makes the overlap window safe even if epoch is rejected (then fall back to `newer_than:1d`).

`Gmail.ListEmails@8.12.1`: params are only `n_emails` (≤100), `page_token`, `exclude_automated` (**default True**), `include_body` (default False). **No query, no time filter.** In 4.2.0 it was `messages.list(q="")` (`tools/gmail.py` L603–628), which includes Butler's own SENT mail. Not suitable for polling.

Automated-sender exclusion (ListEmails, ListEmailsByHeader, ListThreads, SearchThreads; default on): "no-reply sender patterns and Gmail's non-primary category filters (promotions, social, **updates, forums**)". Risks:
- A human guest/host email that Gmail files as `CATEGORY_UPDATES` or `CATEGORY_FORUMS` (multi-recipient group threads can look list-like) would be **silently dropped**. Avoid this by using SearchEmailsByQuery, or pass `exclude_automated=False`.
- Google Calendar RSVP notifications ("Accepted: …", sent on the guest's behalf) and calendar invite mail are exactly what the filter drops. Butler may *not* want them, but don't rely on the filter: see Q6 and the surprises below.

## Q6. `Gmail.GetEmail`: are raw headers (Message-ID, Authentication-Results) returned?

**Answer: Message-ID yes (`header_message_id`), plus `references`. Authentication-Results no. There is no raw-header passthrough.**

- Live S1 `Gmail.GetEmail@8.12.1` (`email_id`) output: `id`, `thread_id`, `label_ids`, `snippet`, `to`, `cc`, `bcc`, `from_`, `reply_to`, `subject`, `body`, `html_body`, `date`, **`header_message_id`**, **`references`**, `email_addresses{from,to,cc,bcc,reply_to}`, `attachments[]` (metadata: `filename`, `mime_type`, …). **No `in_reply_to`** here (SearchEmailsByQuery has it). **No headers map, no `Authentication-Results`/DKIM/SPF.**
- Source confirms the pattern (S3 4.2.0 `models/mappers.py` L42–68): it builds a dict of all headers internally but **returns only** to/cc/from/reply-to/subject/message-id/references.
- Implication: Butler can't verify sender authenticity (spoofed `From: host@…`) through Arcade tools. Partial mitigation: Gmail routes DMARC-failing mail to Spam, and SearchEmailsByQuery excludes spam by default. Full verification would need a custom tool (`messages.get` with `format=metadata` and `metadataHeaders=Authentication-Results`). That's a feature-proposal candidate, not P0.

---

## Live-check list (only a real API call can settle these → ticket 05)

1. **CreateEvent invite email:** does `CreateEvent(attendee_emails=[host], send_notifications_to_attendees="all")` in 4.2.0 actually email the host? (The 3.3.2 source drops `sendUpdates` on insert.) If not, the workaround is create, then `UpdateEvent(attendee_emails_to_add=[host], …="all")`.
2. **Enum value:** `send_notifications_to_attendees="nobody"` is accepted, and `"none"` (from the docs) is rejected or behaves the same?
3. **UpdateEvent add attendee + `all`:** does the new guest get an invite email? Do *existing* guests also get an "Updated invitation" email for a guest-list-only change?
4. **UpdateEvent remove attendee + `all`:** does the removed guest get a cancellation email?
5. **Description-only update + `nobody`:** no email to anyone? And + `all`: does every guest get "Updated invitation"?
6. **ReplyToEmail `every_recipient` + `cc=[new]`:** new person receives it, the message is in the same Butler thread (`thread_id` unchanged), and existing recipients see it threaded in their clients (Gmail + one non-Gmail client if available).
7. **ReplyToEmail on Butler's own message** with `only_the_sender` + `cc`: empty To → error, or sends to Cc only?
8. **ReplyToEmail quoting:** does 8.12.1 still append the quoted original body? Does the subject become "Re: Re: …" on replies to replies?
9. **SearchEmailsByQuery `after:<epoch>`:** the tool passes it through and Gmail filters correctly. Confirm `date` format, and that `-from:me`/`in:inbox` work.
10. **SendEmail `recipient` with a comma-separated list:** does it work? (Optional; `cc` avoids it.)
11. **Deliverability:** do invites and emails from a fresh Butler Gmail account land in guests' Primary inbox, not spam? Do calendar invites from an unknown sender show up? (Google's "only from known senders" calendar setting.)
12. **Calendar side-channel mail into Butler's inbox:** guests clicking Yes/No in the invite produce "Accepted:/Declined:" emails *from the guest's address* to Butler (the organizer). Guests may also hit "reply" on the invite email, which starts a new thread. Check what these look like in SearchEmailsByQuery (subject prefix, `text/calendar` attachment metadata) so the router can skip them or route them.
13. **ReplyToEmail OAuth scopes:** does `calendar.settings.readonly` trigger a separate authorization prompt for Butler's grant?

## Surprises that could change PLAN.md

- **Docs are stale; live catalog is authoritative.** Gmail is 8.12.1 live vs 8.9.1 docs vs 4.2.0 last readable source. Calendar is 4.2.0 live vs 3.7.1 docs vs 3.3.2 source. Pin behavior by live call, not docs. Consider pinning tool versions in `gateway.py` (`Gmail.ReplyToEmail@8.12.1`) if arcadepy allows it.
- **Enum `nobody`, not `none`** for Calendar notifications (live). A wrong value probably fails validation.
- **Default notifications = `all` on every UpdateEvent.** Description re-renders must pass `nobody`, and attendee changes should be split from description changes, or guests get spammed.
- **CreateEvent may not send invites** (3.3.2 bug). Live check #1 decides H2.
- **No Reply-To header support in any Gmail tool.** The D6 relay alternative needs a custom tool. P0 is unaffected.
- **ReplyToEmail `only_the_sender` + explicit `cc`** gives Butler control over its own group-message recipients. This partly fixes D6 drop-out ("Butler stops addressing them" can become "Butler stops sending to them").
- **ReplyToEmail quotes the replied-to message.** Never reply to a private message while cc'ing others. Output token/size grows per reply.
- **Use `SearchEmailsByQuery`, not `ListEmails`, for polling.** ListEmails has no time filter and drops Updates/Forums-category mail by default.
- **No Authentication-Results** anywhere, so sender spoofing can't be checked with catalog tools (feature-proposal candidate alongside D7 triggers).
- **Calendar RSVP buttons are a parallel RSVP channel** Butler can't see by email. `GetEvent` (new in 4.2.0) returns `attendees[].response_status` and `additional_guests`, which could reconcile "No" clicks. Calendar-generated "Accepted:/Declined:" emails will arrive from guest addresses and must not be misread as free-text RSVPs.
