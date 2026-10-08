# Build Group thread

Type: task
Mode: AFK
Status: resolved
Assignee: chrislee (session 2026-10-06)
Blocked by: 11

## Question

PLAN.md build step 4. Group threshold → create Group thread once, late Attending Guests added with a templated welcome (current time, place, Headcount, who's coming; no catch-up summary, cut 2026-10-06), `should_speak` gate, Membership is append-only (design review 2026-10-06): Attending Guests join once with the welcome; declines (email or calendar) never remove anyone. Any Guest posting in the group gets the group toolset; RSVP changes there count (`record_rsvp`, bound to sender) and `should_speak` treats them as speak (G4, G5, G7).
Butler's group posts (D10): `ReplyToEmail` to the newest group message from a current member, `reply_to_whom="only_the_sender"`, `cc` = other current members. Untested: only Butler's opener exists. Live-test `only_the_sender` on Butler's own message (To may be empty) and pick a fallback.
Done when: Group thread starts at threshold and Butler stays silent on chatter.

From [Build Guest flow](11-build-guest-flow.md): `main.converses()` decides what reaches the loop; add the Group thread there. A Group-thread RSVP reuses the Guest path: snapshot the row, loop, `effects.rsvp(store, settings, dinner_id, before)`, reply. Threshold hooks: after `effects.rsvp` (email) and in `sync.apply`'s `moved` list (calendar). `agent.answer` filters `toolset()` to registered tools; register `get_group_thread` to fill the gap. Posting pattern already live: `store.last_from(thread, sender)` + `gateway.reply(..., to_sender_only=True)` (Host notice). Helpers: `store.status`, `store.headcount`, `render.coming`, `render.guest_label`, `tools.public_facts`.

## Answer

Done. Commit eeaa392 on `main` (no co-author line). `uv run pytest`: 82 green (11 new in `tests/test_group.py`).

- **Fallback picked (live, spike `g12_own_reply.py`):** `only_the_sender` on Butler's own email → To = **Butler itself**, Host dropped. `every_recipient` + cc → To = the original To (Host), cc merged, duplicates of To dropped. So Butler's group posts reply to the newest member post (`only_the_sender` + cc = other members), else reply-all to Butler's newest group post (cc = members minus Host). PLAN D10 updated. Fake Gmail now copies both behaviors (pinned test).
- **`effects.join_group(store, settings, dinner_id, now)`:** called after `effects.rsvp` (email) and in `sync.apply` when someone moved (calendar). Threshold reached → opener (`SendEmail` To Host, cc Attending Guests); `group_thread_id` recorded at send. After that, every new Attending Guest → `group_joined_at` + one welcome (time, place, Headcount, who's coming). Membership = Host + `group_joined_at` set (`store.members`), only grows. Calendar No → Yes for a member: nothing.
- **Gate (`butler/gate.py`):** `should_speak(claude, settings, store, dinner_id, email, role, earlier) → (Decision{speak, reason}, shown)`. Sees public facts, last 3 group posts, the new post, sender's role + RSVP status. Structured output (`output_config` json_schema): **Sonnet 5.5 rejects forced `tool_choice`** (400). Traced as `trace.kind = "gate"`, step 0. Silent → marked processed, nothing else.
- **Group loop:** `agent.GROUP` prompt (everyone reads; public facts only; never say who declined; RSVP changes → `record_rsvp`; Dietary needs/notes → "email me privately"; only Host changes the dinner; Host cancel → "confirm privately"). Group tools via `tools.registered(names, channel)`: `get_my_rsvp`/`record_rsvp` group variants have no Dietary needs or notes (`GroupRsvp`). `get_group_thread` registered (`Ctx.gateway`). Reply = `effects.group_reply`: To sender, cc other members, signed on the Host's behalf.
- **New rule (privacy):** a Group-thread email sent only to Butler (Gmail's plain Reply does this) is private: router maps it to `guest_thread`/`host_thread`, reply goes to the sender alone. `router.private(email, butler)` (≤1 reader besides Butler) also filters `agent.history` and `get_group_thread`: group posts never show anyone's private emails; a private email sees only its sender's own. `store.newest_group_post` skips them, so Butler never quotes one to the group. PLAN G5 updated.
- **Moved:** `strip_quote` → `gateway.py` (tools need it; avoids an agent↔tools import cycle). `sync.sync`/`apply` take `now`.

**Live check (run tag g12, script `spike/g12_check.py`, log `/tmp/butler_g12.log`, db `/tmp/butler_g12.db`, threshold 1):** Host setup → "send it" → invites. A "yes" → Group thread opener To Host cc A. B "yes" → welcome To Host cc A+B (reply-all fallback, no member post yet). A reply-all "can't wait! 🎉" → **silent**. B reply-all "Butler, what's parking like?" → speak; reply To B cc Host+A, "street parking only". A plain Reply "I'm vegetarian" → routed private: Dietary needs saved, Host notice, reply To A only. Host reply-all "remind everyone to bring a dish" → speak; post To Host cc A+B. **Done-when met.** Event deleted (`nobody`).

**Leftovers:**
- Gmail's default Reply in the Group thread reaches only Butler → private. Opener says "Reply all to reach everyone"; demo (17) must use Reply all.
- An email in the Group thread to the Host + Butler only (no other Guest) still counts as a group post, so Butler's reply cc's every member. Rare; production fix: reply to exactly who the email reached.
- Speak/silent quality is unmeasured beyond 3 live posts → evals (14).

Time: ~25 min (14:24–14:48).

