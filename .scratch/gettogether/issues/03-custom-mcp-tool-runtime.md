# Custom Arcade MCP tool runtime

Type: research
Mode: AFK
Status: resolved

## Question

If we build a custom tool with arcade-mcp (e.g. `AddAttendee`, `ReplyAll`), how does our Python app call it, and what must a reviewer do to run it?
- `arcade deploy` to Arcade cloud vs local MCP server / worker: which can `arcadepy` `client.tools.execute` reach? Tunnel needed?
- Can a custom tool reuse Arcade's Google auth (`requires_auth=Google(scopes=...)`) so Butler authorizes once?
- Minimal project scaffold + commands (`arcade new`, `arcade deploy`, etc.).
- Reviewer friction for each option.
Conclude with the lowest-friction option for a clone-and-run repo.

## Answer

**Lowest friction: in-process.** Write the tool with arcade-mcp (`@app.tool(requires_auth=Google(scopes=[...]))`, Google call in a plain fn). The app calls that fn with Butler's token from `client.auth.start(BUTLER_USER_ID, "google", SCOPES)`, so it reuses the grant from `authorize.py`. Reviewer has 0 extra steps. Document `arcade deploy` as the optional/production path.

Key facts:
- `tools.execute` reaches only Engine-registered workers: `arcade deploy`, or a hybrid worker at a public URL (tunnel required from a laptop). An unregistered local server can't be reached. Local plain-http blocks auth tools; stdio allows them (single user).
- Google auth reuse works: `Google` uses `provider_id="google"`, the same as catalog Gmail/Calendar. A token is reused if Butler's `user_id` already granted the scopes. `calendar.events` and `gmail.send/readonly/modify` are on the default app's allowed list. Have `authorize.py` request the union of scopes once.
- Tool name for execute: `MCPApp(name="butler_tools")` + `add_attendee` → `ButlerTools.AddAttendee`.
- The catalog may already cover the gaps (`UpdateEvent.attendee_emails_to_add/remove`, `send_notifications_to_attendees`; `ReplyToEmail.reply_to_whom`, `cc`). Ticket 01/05 should confirm before building anything.

Reviewer steps (on top of clone, `.env`, `authorize.py`, run):
- **In-process:** none.
- **Local stdio subprocess** (app spawns `server.py stdio` with `ARCADE_API_KEY` + `ARCADE_USER_ID`): none. Adds an `mcp` client dep and a subprocess.
- **`arcade deploy`:** `uv tool install arcade-mcp`, then `arcade login` (browser; same project as the API key), then `arcade deploy -e src/butler_tools/server.py` (a few minutes; validates by running the server locally). Redeploy on every change. Free-plan deploy limits not stated.
- **Hybrid + tunnel:** install a tunnel tool, set `ARCADE_WORKER_SECRET`, run `server.py http`, start the tunnel, register the URL in the dashboard (or `client.workers.create`, unverified), and re-register on every restart. 3 processes.

Research: [custom-mcp-tool-runtime.md](../research/custom-mcp-tool-runtime.md)

Time: ~40 min.
