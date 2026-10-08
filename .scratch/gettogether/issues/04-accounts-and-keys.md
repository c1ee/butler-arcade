# Accounts and keys

Type: task
Mode: HITL
Status: resolved

## Question

Provision everything the live check and build need (user does this; agent supplies the checklist):
- [x] Butler Gmail account (new)
- [x] Arcade account + API key
- [x] Anthropic API key
- [x] Host account = campingchra@gmail.com (test account, not user's personal)
- [x] Guest accounts A, B, C
- [x] Keys in `.scratch/gettogether/.env` (ARCADE_API_KEY, ANTHROPIC_API_KEY, BUTLER_EMAIL, HOST_EMAIL, GUEST_A/B/C)
Answer records which accounts exist and where secrets live (never the secrets).

## Answer

- Butler `arrialee7@gmail.com`. It's also the Arcade account owner ("Arri's Default project"), and `BUTLER_USER_ID` = that email.
- Host `campingchra@gmail.com`, a test account. Don't use the user's personal Gmail.
- Guests: A `augustclee7@gmail.com`, B `xhakaout32@gmail.com`. C `guest.c.gettogether@outlook.com` (non-Gmail on purpose). C has **no Arcade grant**: Arcade's default Microsoft app supports work/school accounts only ("Personal accounts, such as @outlook.com … cannot authorize"). Getting one would need a custom Azure app registration, which was skipped, so C is observed by hand.
- Secrets live in `.scratch/gettogether/.env` (chmod 600): ARCADE_API_KEY, ANTHROPIC_API_KEY (both verified with a live call), BUTLER_EMAIL/USER_ID, HOST_EMAIL, GUEST_A/B/C.
- Arcade Google grants (Gmail send+readonly, Calendar events+readonly+settings.readonly) exist for Butler, host, A, and B (C: see above). The test-account grants let scripts read inboxes and act as guests.
- **Consent gotcha:** Arcade's default verifier only completes a grant if the browser's Arcade session is the *same account* as the `user_id`. Each test account is a project member with its own Arcade login. Paste the link into that account's browser profile; clicking it from the terminal opens the default profile and the grant silently stays `pending`. → README reviewer setup.
- Local tooling: uv 0.12.23 (brew), Python 3.14 system.
- Butler's Google Calendar timezone is set to Pacific (CreateEvent takes naive datetimes in the calendar's tz).

Time: ~50 min, mostly OAuth troubleshooting.
