# Calendar RSVP responses

Type: grilling
Mode: HITL
Status: resolved
Blocked by: 05

## Question

Attending Guests receive a Google Calendar invite, so they can also answer with the invite's Yes/No/Maybe buttons. Google then sends Butler "Accepted:/Declined:" emails from the Guest's address, and `GetEvent` shows each attendee's response status and extra-guest count. How should Butler treat that channel?
- Honor it (e.g. calendar "No" = Attending → Declined), ignore it, or treat it as a prompt to confirm by email?
- How should the router recognize those notification emails so they aren't read as free-text RSVPs?
- Calendar "Maybe" exists even though P0 is yes/no only. What happens with it?

## Answer

**The calendar decides who's coming** (user, 2026-10-06; replaces an earlier "email only" answer). Guests often RSVP by email, then later switch to No on the calendar without telling anyone.
- **Fact:** Butler can add/remove attendees but can't set a Guest's answer; `RespondToEvent` answers only as Butler. `GetEvent` returns each attendee's `response_status`, `additional_guests`, `comment`.
- **Coming = on the calendar and not declined there.** Yes, Maybe, and awaiting (what an email yes produces) all count. Butler's records hold only Guests not on the calendar (Invited, said no by email) plus a snapshot to diff.
- **Calendar No:** Declined; Headcount re-rendered silently; dropped from Butler's group emails; stays on the calendar so they can switch back. No Host notice (Host can check the calendar), nothing to the Guest, calendar note not stored.
- **Calendar No → Yes:** Attending; group welcome if a group exists; Headcount silent; no Host notice.
- **Email yes after calendar No:** remove + re-add silently → one fresh invite, shown as awaiting.
- **Email no after yes:** removed from calendar silently + the usual thank-you (G3).
- **Maybe:** no-op; counts as coming.
- **Plus-ones:** email only. Calendar "+N" ignored. Syncing it needs a which-channel-wins rule (a guest sets +2 on calendar, later emails "just me") → fast follow.
- **Host notices:** email RSVP changes still notify the Host (they carry Dietary needs and Plus-ones); calendar answers don't.
- **Mechanics:** every poll reads each active Dinner's `GetEvent`, diffs answers vs the snapshot, triggers effects. Google's "Accepted:/Declined:" emails aren't treated as conversation.
- PLAN.md: G1–G4 updated, G7 + D13 added. GLOSSARY: Attending, Declined, Calendar event, Plus-ones.
- Writeup line: guests decline on calendars without telling anyone, so the calendar is the source of truth; Butler can't set answers, so "coming" means on the calendar and not declined there.

Time: ~20 min.

**Amended in design review (2026-10-06):** declines (calendar or email) never remove anyone from the Group thread; switching back gets no new welcome. Butler's cc list therefore never reveals who declined.
