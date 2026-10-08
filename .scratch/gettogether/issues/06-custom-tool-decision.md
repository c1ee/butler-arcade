# Custom tool decision

Type: grilling
Mode: HITL
Status: resolved
Blocked by: 01, 03, 05

## Question

Given the capability gaps found and the runtime cost of a custom tool, do we build one (which, with what interface), or work around gaps with catalog tools? Must also produce the writeup rationale for catalog-vs-custom (rubric asks for it explicitly).

## Answer

**Catalog only. No custom tool.**

- **Gaps a custom tool would close:**
  - Exact thread recipients. `ReplyToEmail` takes To from the replied-to message, quotes it, and has no Reply-To.
  - Sender authentication. No tool exposes SPF/DKIM/DMARC.
  - Neither is P0.
- **Group recipients (P0 workaround):** Butler replies to the newest group message from a current member, with `reply_to_whom="only_the_sender"` + `cc` = other current members. Dropped guests stop getting Butler's posts. Costs: quotes the replied-to message; no relay.
  - Untested: only Butler's opener exists, so To may come out empty. Ticket 12 tests it live and needs a fallback.
- **Faked sender:** out of scope for the demo. One line in WRITEUP's production section.
- **Domain tools** (`record_rsvp`, `get_guest_details`, …) stay app-internal Python fns (timebox). The audience-scoped argument goes to ticket 15, not here.
- **Reviewer setup:** `authorize.py` requests catalog scopes only. No extra steps, no `tools/` dir.

**WRITEUP rationale (draft):**
> The live check showed the catalog (Gmail 8.12.1, Calendar 4.2.0) covers every effect Butler needs: sending invites, adding or removing a guest (only that guest is notified), re-rendering the description silently, private threads, and adding people to the group via Cc. A custom tool would close two gaps. First, exact thread recipients: the reply tool takes To from the email being replied to and has no Reply-To. Second, sender authentication: no tool exposes auth headers. Neither is P0. We work around recipients by replying to the newest current member, and spoofing is deferred. Production: `ReplyInThread(to, cc, reply_to)` makes the relay group (D6) possible, and a DMARC check makes identity binding (D4) actually trustworthy.

Time: ~30 min (≈10:12–10:42, 2026-10-06).
