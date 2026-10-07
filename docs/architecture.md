# GetTogether — Architecture

How Butler is built, as of the submission. Terms are capitalized when they have a precise meaning (Host, Guest, Dinner, Attending, Group thread, ...). The reasoning behind each decision is in [WRITEUP.md](../WRITEUP.md); D1–D15 are indexed at the end.

**Contents**

1. [Overview](#1-overview)
2. [System context](#2-system-context)
3. [Components](#3-components)
4. [Message pipeline](#4-message-pipeline)
5. [Sequences](#5-sequences)
6. [State machines](#6-state-machines)
7. [Data model](#7-data-model)
8. [Trust and privacy](#8-trust-and-privacy)
9. [Decision index](#9-decision-index)

---

## 1. Overview

**Problem.** Dinner parties stall on logistics: chasing RSVPs, collecting Plus-ones and Dietary needs, answering the same questions, keeping everyone updated. **Butler** is an organizer with its own Gmail and Calendar. Hosts and Guests only ever email it; nobody but Butler logs in to anything.

**Built**

| Host | Guest |
|---|---|
| H1 Setup by email; Butler asks for what's missing and shows a draft | G1 RSVP yes/no by email; yes puts them on the Calendar event |
| H2 Approve; Butler creates the Calendar event and emails each Guest privately | G2 Plus-ones, Dietary needs and a note for the Host from the same email |
| H3 Group thread starts at the Group threshold; latecomers get a welcome | G3 Decline gets a thank-you; changing their mind works |
| H4 Changes reach the calendar, the Group thread, and Guests outside it once | G4 Dropping out by email takes them off the calendar; they stay in the Group thread |
| H5 Ask anything; full answers only in the Host thread | G5 Butler stays quiet in the group unless it has a reason to speak |
| H6 Host notes, shareable or private, fixable later | G6 Ask anything; answers only from what Guests may see |
| H8 Cancel, after Butler asks to confirm | G7 Calendar Yes/No/Maybe buttons count; the calendar decides who's coming |

**Fast follows** (designed, not built): Escalations (H7: forward a question Butler can't answer to the Host and relay the answer), Uninvite (H9), catch-up summary for late joiners, calendar "+N" as Plus-ones, nudges, day-of logistics email, +1 policy, personality, multiple Dinners, relay Group thread.

---

## 2. System context

```mermaid
flowchart LR
  Host(["Host"])
  Guests(["Guests"])
  subgraph Google["Google (Butler's account)"]
    Gmail["Butler's Gmail"]
    Cal["Butler's Calendar"]
  end
  Arcade["Arcade<br/>OAuth + catalog tools<br/>Gmail 8.12.1, GoogleCalendar 4.2.0"]
  subgraph Local["Butler process (local)"]
    Butler["Butler"]
    DB[("SQLite<br/>private state")]
  end
  Claude["Claude API<br/>claude-sonnet-5-5"]

  Host -- "email" --> Gmail
  Guests -- "email" --> Gmail
  Gmail -- "email" --> Host
  Gmail -- "email" --> Guests
  Cal -- "invites" --> Guests
  Guests -- "Yes / No / Maybe" --> Cal
  Butler -- "tools.execute (user_id = Butler)" --> Arcade
  Arcade --> Gmail
  Arcade --> Cal
  Butler <--> DB
  Butler -- "messages + domain tools" --> Claude
```

- One Google account (Butler's), authorized once through Arcade (D1). Hosts and Guests authorize nothing.
- Butler polls; nothing pushes to it (D7).
- Claude never talks to Arcade. It calls Butler's domain tools; Butler's code calls Arcade (D2).

---

## 3. Components

```mermaid
flowchart TD
  main["main.py<br/>poll loop + tick"]
  router["router.py<br/>email → Dinner, channel, role"]
  gate["gate.py<br/>should_speak"]
  agent["agent.py<br/>tool loop, cap 6, traces"]
  tools["tools.py<br/>domain tools + toolset(role, channel, phase)"]
  sync["sync.py<br/>calendar read + diff"]
  effects["effects.py<br/>Change → outbox → send"]
  render["render.py<br/>templates"]
  store["store.py<br/>SQLite"]
  gateway["gateway.py<br/>only Arcade caller"]
  arcade[["arcadepy"]]
  anthropic[["anthropic SDK"]]

  main --> gateway
  main --> router
  main --> gate
  main --> agent
  main --> sync
  main --> effects
  router --> store
  gate --> anthropic
  agent --> anthropic
  agent --> tools
  tools --> store
  tools --> effects
  sync --> gateway
  sync --> effects
  effects --> render
  effects --> store
  effects --> gateway
  gateway --> arcade
```

| Module | Owns | Never does |
|---|---|---|
| `router` | Which Dinner, channel (Host / Guest / Group thread), and role (Host / Guest / stranger) an email belongs to, from thread id and sender. Skips Google's and Outlook's Accepted/Declined emails. A Group thread email sent only to Butler is private. | Read the email body |
| `gate` | One structured Claude call: speak or stay silent in the Group thread | Act on anything |
| `agent` | The tool loop: system prompt, thread history, scoped tools, iteration cap, traces | Choose recipients or call Arcade |
| `tools` | Domain tools and which ones exist for (role, channel, phase) | Return data outside the reader's scope |
| `sync` | Per-poll calendar read; turns answer changes into Changes | Email anyone |
| `effects` | Turns an email's net Change into outbox rows; sends pending rows; marks them sent | Decide what the email meant |
| `render` | Every system email, the draft preview and the Calendar description, as templates | Use Claude |
| `store` | SQLite reads/writes, one transaction per processed email | Talk to the network |
| `gateway` | The only module that calls Arcade; normalizes field names | Hold business rules |

**Gateway methods** (the seam tests replace with a fake that mimics real Gmail's recipient derivation and quoting)

| Method | Arcade tool | Notes from the live check |
|---|---|---|
| `search_inbox(after)` → emails | `Gmail.SearchEmailsByQuery` | `in:inbox after:<epoch>`, re-reading 120s back because Gmail indexes some email late; dedupe by message id |
| `get_thread(thread_id)` → emails | `Gmail.GetThread` | Thread history for every Claude call (last 10), and `get_group_thread` |
| `send(to, subject, body, cc)` → message id, thread id | `Gmail.SendEmail` | One `recipient` + `cc`; comma-separated recipients land in spam |
| `reply(message_id, body, cc, to_sender_only)` → message id, thread id | `Gmail.ReplyToEmail` | Quotes the replied-to email; To comes from it; can't set the subject |
| `create_event(title, start, end, place, description, host)` → event id | `GoogleCalendar.CreateEvent` | Notify `all`: Host gets the invite |
| `get_event(event_id)` → attendees + answers | `GoogleCalendar.GetEvent` | `response_status` per attendee |
| `update_event(event_id, start?, place?, description?)` | `GoogleCalendar.UpdateEvent` | Notify `nobody`; returns a string |
| `add_attendee(event_id, email)` | `GoogleCalendar.UpdateEvent` | Notify `all`: only that Guest is emailed |
| `remove_attendee(event_id, email)` | `GoogleCalendar.UpdateEvent` | Notify `nobody` |
| `delete_event(event_id)` | `GoogleCalendar.DeleteEvent` | Notify `nobody`; still takes it off attendees' calendars |

---

## 4. Message pipeline

```mermaid
flowchart TD
  poll["Poll Butler's inbox every POLL_SECONDS (30)<br/>in:inbox after:last poll − 120s"] --> seen{"Message id<br/>already processed?"}
  seen -- yes --> skip1["Skip"]
  seen -- no --> route["Route by thread id, then sender"]
  route --> kind{"What is it?"}
  kind -- "Google Accepted/Declined email" --> skip2["Mark processed, skip<br/>(calendar read catches it)"]
  kind -- "unknown sender" --> skip3["Mark processed, ignore"]
  kind -- "Host / Guest thread, or a Group thread email sent only to Butler" --> strip["Strip pasted quote, load last 10 thread messages"]
  kind -- "Group thread (sent to more than Butler)" --> strip
  strip --> isgroup{"Group thread?"}
  isgroup -- yes --> gate{"should_speak"}
  gate -- silent --> done1["Mark processed"]
  gate -- speak --> loop
  isgroup -- no --> loop["Tool loop<br/>toolset(role, channel, phase), max 6 steps"]
  loop --> tx["One transaction:<br/>state changes + Change rows + outbox rows (incl. reply) + mark processed"]
  tx --> flush["Send pending outbox rows, mark each sent"]

  tick["Every poll, per active Dinner"] --> read["sync: GetEvent, diff answers vs snapshot"]
  read --> diff{"Anything changed?"}
  diff -- yes --> tx2["Transaction: statuses + Changes + outbox rows"] --> flush
  diff -- no --> close
  tick --> close{"Past start + 1h?"}
  close -- yes --> closed["Dinner closed; later emails ignored"]
```

**Why this order:** effects and outbox rows commit together with "processed", so every email is acted on exactly once. Sending is separate and retried from the outbox, so every recipient gets each message exactly once (D5).

---

## 5. Sequences

### 5a. Setup and approval (H1, H2)

```mermaid
sequenceDiagram
  actor Host
  participant Gmail as Butler's Gmail
  participant Butler
  participant Claude
  participant Cal as Butler's Calendar
  actor Guests

  Host->>Gmail: "Dinner Sat 7pm, invite a, b, c"
  Butler->>Gmail: poll
  Note over Butler: No active Dinner, so new draft. Setup toolset has update_draft only
  Butler->>Claude: email + update_draft
  Claude->>Butler: update_draft(start, guests)
  Claude-->>Butler: reply asking where
  Butler->>Gmail: reply in Host thread
  Host->>Gmail: "at mine, 12 Elm St"
  Butler->>Claude: email + update_draft
  Claude->>Butler: update_draft(place)
  Note over Butler: Draft complete, so code appends the rendered preview and marks it shown
  Butler->>Gmail: reply with draft preview
  Host->>Gmail: "looks good, send it"
  Note over Butler: Draft was shown, so send_invites now exists (D9)
  Butler->>Claude: email + update_draft, send_invites
  Claude->>Butler: send_invites()
  Note over Butler: Dinner active. Outbox gets event + one invite per Guest + reply
  Butler->>Cal: CreateEvent (Host only, notify all)
  Cal-->>Host: calendar invite
  Butler->>Gmail: SendEmail invite, once per Guest
  Gmail-->>Guests: private invite emails
  Butler->>Gmail: reply to Host "invites sent"
```

### 5b. Guest says yes and asks a question (G1, G2, G6)

```mermaid
sequenceDiagram
  actor A as Guest A
  participant Gmail as Butler's Gmail
  participant Butler
  participant Claude
  participant Cal as Butler's Calendar
  actor Host

  A->>Gmail: "yes! bringing my partner, she's vegetarian. parking?"
  Butler->>Gmail: poll
  Note over Butler: Thread id, so A's Guest thread, role Guest (Invited). Scope is public + own
  Butler->>Claude: email + get_event, get_my_rsvp, record_rsvp
  Claude->>Butler: record_rsvp(attending, plus_ones 1, dietary vegetarian)
  Claude->>Butler: get_event()
  Butler-->>Claude: time, place, Headcount, shareable notes (street parking only)
  Claude-->>Butler: reply "You're in. Street parking only."
  Note over Butler: One transaction: A yes, outbox gets add attendee, description, reply, Host notice
  Butler->>Cal: add A (notify all)
  Cal-->>A: calendar invite (shows awaiting, counts as coming)
  Butler->>Cal: description with new Headcount (notify nobody)
  Butler->>Gmail: reply to A
  Butler->>Gmail: Host notice in Host thread (A +1, vegetarian)
```

Claude never sees B's or C's Dietary needs here: no tool in A's toolset returns them (D3).

### 5c. Group threshold, chatter, late joiner (H3, G5)

```mermaid
sequenceDiagram
  actor B as Guest B
  actor A as Guest A
  actor C as Guest C
  participant Gmail as Butler's Gmail
  participant Butler
  participant Claude

  B->>Gmail: "yes"
  Butler->>Claude: record_rsvp(attending)
  Note over Butler: Attending count reaches the threshold (2)
  Butler->>Gmail: SendEmail to Host, cc A and B (group opener template)
  Note over Butler: Stores the Group thread id
  A->>Gmail: "can't wait!" (reply-all in group)
  Butler->>Claude: should_speak
  Claude-->>Butler: silent
  A->>Gmail: "Butler, what time again?"
  Butler->>Claude: should_speak
  Claude-->>Butler: speak
  Butler->>Claude: tool loop, Group toolset, public scope
  Butler->>Gmail: reply to A's email, to sender only, cc Host and B
  C->>Gmail: "actually I'm in" (C's Guest thread)
  Butler->>Claude: record_rsvp(attending)
  Butler->>Gmail: reply to C in C's Guest thread
  Butler->>Gmail: reply to newest member email, to sender only, cc everyone else + C (welcome template with time, place, Headcount, who's coming)
```

### 5d. Host Change reaches everyone once (H4)

```mermaid
sequenceDiagram
  actor Host
  participant Gmail as Butler's Gmail
  participant Butler
  participant DB as SQLite
  participant Cal as Butler's Calendar

  Host->>Gmail: "move it to 8pm" (Host thread)
  Butler->>Butler: tool loop, change_event(start 20:00)
  Butler->>DB: one transaction: Dinner time, Change row, outbox rows, message processed
  Note over DB: Outbox rows keyed (change, channel, recipient): calendar, Group thread, each Invited or Attending Guest outside it, reply to Host
  loop each pending row
    Butler->>Cal: update time (notify nobody)
    Butler->>Gmail: group post with Change notice
    Butler->>Gmail: private Change notice per Guest outside the group
    Butler->>Gmail: reply to Host "done"
    Butler->>DB: mark row sent
  end
  Note over Butler,DB: Crash mid-loop: the next poll sends only rows still pending. The email is never re-run
```

Before the Group thread exists, every Invited and Attending Guest gets the Change privately. If the Host made the Change in the Group thread, the notice rides on Butler's reply there instead of a second post. One Host email is one Change, however many tool calls it took: `effects.host_changes` diffs the Dinner before and after the loop.

### 5e. A Guest declines on the calendar (G7, D13)

```mermaid
sequenceDiagram
  actor B as Guest B
  participant Cal as Butler's Calendar
  participant Gmail as Butler's Gmail
  participant Butler

  B->>Cal: clicks No
  Cal-->>Gmail: "Declined: Dinner" from B (new thread)
  Butler->>Gmail: poll
  Note over Butler: Router sees a calendar notification, marks it processed, skips it
  Butler->>Cal: sync, GetEvent
  Cal-->>Butler: B declined (snapshot said awaiting)
  Note over Butler: B is now Declined (still on the calendar). Change, outbox gets the description only
  Butler->>Cal: description with lower Headcount (notify nobody)
  Note over Butler: No emails. B stays in the Group thread
```

### 5f. Cancel (H8)

```mermaid
sequenceDiagram
  actor Host
  participant Gmail as Butler's Gmail
  participant Butler
  participant Claude
  participant Cal as Butler's Calendar
  actor Guests

  Host->>Gmail: "cancel the dinner" (Host thread)
  Butler->>Claude: Host toolset without cancel_dinner
  Claude->>Butler: ask_cancel_confirmation()
  Note over Butler: Dinner is ConfirmingCancel. The window is the Host's next email
  Claude-->>Butler: reply asking to confirm
  Butler->>Gmail: reply "Cancel Saturday's dinner? Everyone still invited will be told."
  Host->>Gmail: "yes"
  Butler->>Claude: Host toolset now includes cancel_dinner
  Claude->>Butler: cancel_dinner()
  Note over Butler: Dinner canceled. Outbox gets one cancel message per Invited or Attending Guest, delete event, reply
  Butler->>Gmail: group post if a Group thread exists (covers its members)
  Butler->>Gmail: private cancel message to each Invited or Attending Guest not in the group
  Gmail-->>Guests: one cancel message each (the group post reaches Declined members too)
  Butler->>Cal: DeleteEvent (notify nobody)
  Butler->>Gmail: reply to Host "canceled"
```

In the Group thread, "cancel" from the Host gets "please confirm with me privately" and nothing changes.

---

## 6. State machines

### Dinner

```mermaid
stateDiagram-v2
  [*] --> Draft: Host emails Butler, no active Dinner
  Draft --> DraftShown: draft complete, preview sent
  DraftShown --> Draft: Host edits the draft
  DraftShown --> Active: send_invites
  Active --> ConfirmingCancel: Host asks to cancel
  ConfirmingCancel --> Canceled: Host confirms, cancel_dinner
  ConfirmingCancel --> Active: any other Host message
  Active --> Closed: start + 1h
  Canceled --> [*]
  Closed --> [*]
```

Tools follow state (D9): `send_invites` only in DraftShown, `cancel_dinner` only in ConfirmingCancel. Canceled and Closed Dinners ignore new emails.

### Guest

```mermaid
stateDiagram-v2
  state "Invited (not on calendar)" as Invited
  state "Attending (on calendar, Yes / Maybe / awaiting)" as Attending
  state "Declined by email (off calendar)" as DeclinedOff
  state "Declined on calendar (still on it)" as DeclinedOn

  [*] --> Invited: invite email sent
  Invited --> Attending: email yes, added to calendar
  Invited --> DeclinedOff: email no, thank-you
  Attending --> Attending: calendar Yes or Maybe, no-op
  Attending --> DeclinedOn: calendar No, silent
  Attending --> DeclinedOff: email no, removed silently + thank-you
  DeclinedOn --> Attending: calendar Yes or Maybe, silent
  DeclinedOn --> Attending: email yes, removed + re-added
  DeclinedOff --> Attending: email yes, added to calendar
```

A Guest joins the Group thread (with the welcome) the first time they're Attending after it starts, and never leaves it. Host notices go out for email transitions only; calendar transitions are silent (D13).

---

## 7. Data model

```mermaid
erDiagram
  DINNER ||--o{ GUEST : invites
  DINNER ||--o{ HOST_NOTE : has
  DINNER ||--o{ CHANGE : records
  CHANGE ||--o{ OUTBOX : "fans out to"
  DINNER ||--o{ MESSAGE : "routes to"
  MESSAGE ||--o{ TRACE : "loop steps"

  DINNER {
    int id PK
    string status "draft/draft_shown/active/confirming_cancel/canceled/closed"
    string title
    string host_email
    string host_name
    datetime start_at
    string place
    int group_threshold
    string calendar_event_id
    string host_thread_id
    string group_thread_id
    string cancel_asked_in "Host email that opened the window"
  }
  GUEST {
    int id PK
    int dinner_id FK
    string email
    string name
    string email_answer "none/yes/no"
    bool on_calendar
    string calendar_answer "last snapshot"
    int plus_ones
    string dietary_needs
    string guest_note
    string guest_thread_id
    datetime group_joined_at
  }
  HOST_NOTE {
    int id PK
    int dinner_id FK
    string text
    bool shareable
    bool deleted
  }
  CHANGE {
    int id PK
    int dinner_id FK
    string kind "approve/rsvp/group_start/group_join/change/cancel"
    json payload
  }
  OUTBOX {
    int id PK
    int change_id FK "null for a reply"
    string message_id "the email it answers"
    string channel "calendar/host/guest/group"
    string recipient
    json payload
    string status "pending/sent"
    string sent_message_id
  }
  MESSAGE {
    string gmail_message_id PK
    string thread_id
    string sender
    int dinner_id FK
    string channel
    string role
    string skipped "why not acted on"
    datetime processed_at
  }
  TRACE {
    int id PK
    string gmail_message_id FK
    int step
    string kind "claude/tool/gate"
    json input
    json output
  }
```

- `OUTBOX` rows belong to a Change, unique on (change, channel, recipient), or answer one inbound email, unique on (message, channel, recipient) (D5).
- Group thread members = Host + Guests with `group_joined_at` set. It's never cleared.
- **A Guest's status is derived, never stored** (D13): on the calendar → Declined if `calendar_answer` is declined, else Attending. Off the calendar → Declined if `email_answer` is no, else Invited.

**What lives on the Calendar event instead**

| Calendar field | Comes from | Who's notified when it changes |
|---|---|---|
| Title, start, end (start + 3h), location | Dinner | nobody (Butler sends its own notice) |
| Description | Rendered from public scope: time, place, Headcount, shareable Host notes | nobody |
| Attendees + answers | Host, Attending Guests, Guests who declined on the calendar. **Source of truth for who's coming** | Added Guest only; removals silent |

---

## 8. Trust and privacy

```mermaid
flowchart LR
  subgraph Untrusted
    E["Email body, quoted history, signatures"]
    F["From header (forgeable; out of scope for the demo)"]
    M["Claude's tool arguments and reply text"]
  end
  subgraph Code["Enforced in code"]
    R["Router: role from sender address, never from content"]
    T["Toolset: role x channel x phase (D4, D9)"]
    S["Scoped reads: min(asker, audience) (D3)"]
    V["Tool arguments validated (pydantic)"]
    P["Recipients chosen by code, never by Claude"]
    Q["Pasted quotes stripped; history from the real thread, labeled by sender (D15)"]
  end
  subgraph Checked["Checked in every test and eval run (D12)"]
    I["Input check: nothing shown to Claude is outside the reader's audience"]
    O["Output check: nothing sent is outside each recipient's audience"]
  end
  F --> R --> T --> S
  E --> Q --> M
  M --> V --> P
  S --> I
  P --> O
```

**Scopes** (who may read what)

| Scope | Contents | Readable in |
|---|---|---|
| public | time, place, Headcount, Attending names, shareable Host notes | everywhere |
| group | Group thread emails | Host thread, Attending Guest's thread, Group thread |
| own | the asking Guest's answer, Plus-ones, Dietary needs, Guest note | that Guest's thread |
| private | every Guest's details, private Host notes, Invited and Declined names | Host thread only |

Scope = min(asker, audience): the Host asking in the Group thread gets public + group only, because Guests read the answer.

**Toolsets**

| Tool | Host thread | Host in Group thread | Attending Guest (own thread) or any Guest in Group thread | Invited or Declined Guest (own thread) |
|---|---|---|---|---|
| `get_event` (public) | ✓ | ✓ | ✓ | ✓ |
| `get_group_thread` | ✓ | ✓ | ✓ | |
| `get_my_rsvp` | | | ✓ | ✓ |
| `get_guest_details` (private) | ✓ | | | |
| `record_rsvp(attending, plus_ones?, dietary_needs?, note_for_host?)`, bound to sender; in the Group thread only `attending` and `plus_ones` | | | ✓ | ✓ |
| `change_event(start?, place?)` | ✓ | ✓ | | |
| `add_note(text, shareable)` | ✓ | ✓ | | |
| `invite_guest(email)` | ✓ | ✓ | | |
| `update_note(note, shareable? or delete)` | ✓ | | | |
| `ask_cancel_confirmation()`, opens the cancel window | ✓ | | | |
| `cancel_dinner()`, ConfirmingCancel only | ✓ | | | |
| Setup phase: `update_draft(...)`; `send_invites()` once the draft was shown | ✓ | | | |

**Secrets and their audiences** (the evals' Planted secrets): Dietary needs and Guest notes (Host + that Guest), private Host notes (Host), Invited and Declined identities (Host + that Guest). Never secret: time, place, Attending names, Headcount, shareable Host notes.

---

## 9. Decision index

| # | Decision | One line |
|---|---|---|
| D1 | Butler has its own Google identity | One Arcade grant; Hosts and Guests authorize nothing |
| D2 | Tool loop for conversation, workflow for effects | Compound emails need a loop; the per-role toolset is the permission model |
| D3 | Privacy by construction | Scope = min(asker, audience); no tool returns what the reader can't see |
| D4 | Identity bound by code | `record_rsvp` writes for the sender; Host tools absent from Guest toolsets |
| D5 | Idempotent effects via outbox | Rows keyed (change, channel, recipient); dedupe inbound by message id |
| D6 | Group thread = reply-all with Butler-controlled cc | Relay design is the production upgrade |
| D7 | Polling, not push | 30s poll; Arcade has no inbound trigger (the feature proposal) |
| D8 | Templates for system emails, Claude for conversation | Predictable, testable notices |
| D9 | State-dependent toolsets | Approval and cancel confirmation enforced by which tools exist |
| D10 | Catalog tools only | Gaps (exact recipients, sender authentication) aren't P0 |
| D11 | Evals in pytest | `arcade evals` can't see the loop or the reply, where privacy bugs live |
| D12 | Privacy checked on input and output | Zero tolerance; over-refusal fails too |
| D13 | The calendar decides who's coming | Coming = on it and not declined there; Butler can't set answers |
| D14 | One Dinner at a time | Everything is keyed by Dinner; multiple Dinners mostly means routing fresh emails |
| D15 | Context from the real thread, not pasted quotes | Labeled by real sender, can't be forged, holds only what the thread's readers already got |
