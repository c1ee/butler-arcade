# Custom Arcade MCP tool runtime

Ticket: [03-custom-mcp-tool-runtime](../issues/03-custom-mcp-tool-runtime.md). Researched 2026-10-05.

Sources pinned:
- Docs source `ArcadeAI/docs` @ `a6b3f85` (2026-10-02). Doc pages map to `https://docs.arcade.dev/en/<path>` (the file is `app/en/<path>/page.mdx`).
- `ArcadeAI/arcade-mcp` @ `78e9820` (2026-10-02). Paths below are relative to that repo; GitHub: `https://github.com/ArcadeAI/arcade-mcp/blob/78e9820/<path>`.
- PyPI (2026-10-05): `arcade-mcp` 1.16.1 (CLI), `arcade-mcp-server` 1.32.1, `arcade-core` 4.22.0, `arcadepy` 1.10.0. All need Python >=3.10 except arcadepy (>=3.8).
- Arcade Engine OpenAPI: `https://api.arcade.dev/v1/swagger`.

No live calls were made: there are no Arcade credentials on this machine. Items marked **unverified** go to the live check (ticket 05).

## TL;DR

- `client.tools.execute` only reaches tools that the Arcade **Engine** knows about, meaning a worker registered in the caller's project. There are two ways to register one: `arcade deploy` (Arcade hosts it) or a hybrid worker (you host it, and Arcade Cloud must reach it at a **public URL**, so a laptop needs a tunnel). An unregistered local server (stdio or plain http) is **not** reachable through `tools.execute`.
- **Google auth reuse: yes.** `Google(scopes=[...])` uses `provider_id="google"`, the same provider every catalog Gmail/Calendar tool uses. Tokens come from the per-user token vault, so if Butler's `user_id` has already granted the needed scopes, a custom tool gets the token without a new consent. This holds on every runtime (deployed, hybrid, local stdio, in-process via `client.auth.start`).
- **Lowest friction for clone-and-run:** run the custom tool logic **in-process**. Get Butler's Google token from `client.auth.start(user_id, "google", scopes)`, which reuses the grant `scripts/authorize.py` already made, and call the tool function directly. The reviewer has no extra steps. Next best is the local stdio MCP subprocess (also no extra steps). `arcade deploy` costs the reviewer a CLI install, a browser `arcade login`, and a deploy of a few minutes. A hybrid worker with a tunnel is the worst option.
- **Possible PLAN change:** the catalog already appears to cover the two example gaps. `GoogleCalendar.UpdateEvent` has `attendee_emails_to_add` / `attendee_emails_to_remove` / `send_notifications_to_attendees`, and `Gmail.ReplyToEmail` has `reply_to_whom` + `cc` (see "Catalog check" below). A custom tool may not be needed at all. Ticket 01/05 decides.

## 1. Which runtimes can `arcadepy` `client.tools.execute` reach?

### How execution is routed
- The Engine "calls MCP servers over HTTP to execute tools"; "MCP servers appear as **workers** … in the Engine's API" (`operate/deploy/architecture`, sections "Engine" and "MCP servers"). There are three sources: the bundled catalog server, "MCP servers you write and deploy", and registered remote servers. In every case "the Engine sends the tool call over HTTP with the end-user credential from the token vault".
- `client.tools.execute()`: "Arcade: 1. Checks for authorization. 2. Routes the request to the tool's provider. 3. Returns the tool's response." (`build/tool-calling/custom-apps/auth-tool-calling`).
- Conclusion: `tools.execute` can only target tools in the project's catalog, which means tools served by a registered worker.

### Option A: `arcade deploy` (Arcade-hosted)
- "Your MCP server will be registered to Arcade, adding all the tools you created to the larger tool catalog … You can use any of the available Arcade clients to call the tools in your MCP Server. When using the clients, you are not required to create an MCP Gateway" (`build/arcade-deploy`).
- The compare table lists "http | Arcade Cloud" as supporting secrets, auth (single-user), and auth (multi-user) (`build/create-tools/tool-basics/compare-server-types`).
- Reachable via `tools.execute`: **yes**. A tunnel is not needed.

### Option B: hybrid worker (self-hosted, registered with Arcade Cloud)
- "You can make your self-hosted MCP server accessible to Arcade Cloud by exposing it through a secure tunnel and registering it as a worker … Your MCP server is exposed to Arcade's cloud engine using a public URL. The Arcade cloud engine routes tool calls to your MCP server" (`operate/deploy/on-prem`, "How on-premises MCP servers work").
- Steps from that page: run `uv run server.py http`; open a tunnel (ngrok / `cloudflared tunnel --url http://localhost:8000` / Tailscale Funnel); then in the dashboard choose "Add Server" with type "Arcade", the URL, a secret, a timeout, and a retry count.
- Code: worker routes `/worker/*` (the protocol the Engine speaks) exist only when `ARCADE_WORKER_SECRET` is set (`libs/arcade-mcp-server/arcade_mcp_server/worker.py:238-246`; `settings.py:388-392` aliases `server_secret` to `ARCADE_WORKER_SECRET`).
- Registration can also be scripted. The Engine has `POST /v1/workers` with body `{id, type, http:{uri, secret, timeout, retry}}` (OpenAPI `schemas.CreateWorkerRequest` / `HTTPWorkerConfigRequest`), and arcadepy exposes it as `client.workers.create(...)` / `.update(...)` (`arcadepy/resources/workers.py`, v1.10.0). The endpoint is tagged "Admin". Whether a normal project API key may call it is **unverified**.
- Tunnel: **required** for a laptop. I found no reverse/outbound-connection feature in the docs or the arcade-mcp source; `tunnel` appears only on the on-prem page. Free ngrok/quick-tunnel URLs change on restart (on-prem page, "Cons"), so the worker URL has to be updated on every run.
- Reachable via `tools.execute`: **yes**, while the tunnel and the server are both up.

### Option C: local server that is not registered (stdio or plain http)
- The Engine has no route to it, so `tools.execute` **cannot** reach it. Your own process has to talk MCP to it directly.
- stdio: auth tools and secrets work locally in single-user mode (compare table row "stdio | local": ✅ secrets, ✅ auth single-user, ❌ multi-user).
- Plain local http: auth tools and secrets are **blocked**. "For security reasons, Local HTTP servers do not currently support tool-level authorization and secrets" (`build/create-tools/tool-basics/build-mcp-server`). Code: `_check_transport_restrictions` returns "Unsupported transport" for any non-stdio session whose tool needs auth or secrets, unless front-door Resource Server auth is on (`libs/arcade-mcp-server/arcade_mcp_server/server.py:1757-1806`). Startup warning: `mcp_app.py:608`. The generated template says the same: http "Does not support tools that require_auth or require_secrets unless the server is deployed using 'arcade deploy' or added in the Arcade Developer Dashboard with 'Arcade' server type" (`libs/arcade-cli/arcade_cli/templates/minimal/{{ toolkit_name }}/src/{{ toolkit_name }}/server.py:85-91`).

### Option D: in-process (no MCP, no Arcade routing)
- Arcade documents getting a user's token from Arcade and calling the third-party API yourself, "without using Arcade for tool execution or definition": `client.auth.start(user_id=..., provider="google", scopes=[...])`, then use `auth_response.context.token` with `google.oauth2.credentials.Credentials` (`build/tool-calling/call-third-party-apis`).
- An `@app.tool`-decorated function is still an ordinary callable. `MCPApp.add_tool` returns `func` (`mcp_app.py:374`). The tool body only reads `context.get_auth_token_or_empty()` / `context.authorization.token`, and those also exist on the plain `arcade_core.schema.ToolContext`. The cleaner pattern is to put the Google API logic in a plain function `fn(token, ...)` and call it from both the `@app.tool` wrapper and the app.

### Tool naming for `tools.execute`
- The toolkit name is normalized to PascalCase (`normalize_toolkit_name` = snake→Pascal, `libs/arcade-core/arcade_core/utils.py:46-53`, applied at `catalog.py:557`). Tool function names are converted with `snake_to_pascal_case` (`catalog.py:562`). So `MCPApp(name="butler_tools")` + `def add_attendee` → `ButlerTools.AddAttendee`.

## 2. Can a custom tool reuse Butler's Google authorization?

**Yes, on every runtime, as long as the Arcade project and `user_id` are the same and the scopes have already been granted.**

- The provider is the same. `class Google(OAuth2): provider_id = "google"` (`libs/arcade-core/arcade_core/auth.py:126-132`). The catalog tools also declare `providerId: "google"`. Examples: `Gmail.SendEmail` uses `gmail.send`, `Gmail.ReplyToEmail` uses `gmail.send`+`gmail.readonly`, and `GoogleCalendar.UpdateEvent` uses `calendar.events` (docs repo `toolkit-docs-generator/data/toolkits/gmail.json` v8.9.1, `googlecalendar.json` v3.7.1).
- Grants are reused. "When the tool is invoked, Arcade checks if the user has already authorized the scopes required by the tool. If the tool's requirements are not met, Arcade initiates the provider-specific OAuth flow" … "Arcade also remembers the user's authorization tokens, so they won't have to go through the authorization process again until the token is revoked" (`build/create-tools/tool-basics/create-tool-auth`). The Google provider page has a section "Using Google auth in custom tools" with `requires_auth=Google(scopes=[...])` and `context.authorization.token` (`references/auth-providers/google`).
- The default Arcade Google app allows a fixed scope list that includes `calendar.events`, `gmail.send`, `gmail.readonly`, `gmail.compose`, and `gmail.modify`. Any scope outside that list returns `400 … requesting scopes not allowed for this provider` (`references/auth-providers/google`, "Supported scopes"). An AddAttendee/ReplyAll tool needs no new scopes and no custom OAuth app.
- How each runtime obtains the token:
  - Deployed / hybrid: the Engine attaches "the end-user credential from the token vault" for the `user_id` passed to `tools.execute` (architecture page). The worker receives it in `ToolCallRequest.context` (`libs/arcade-serve/arcade_serve/core/base.py:109-160`).
  - Local stdio: the server calls `self.arcade.auth.authorize(auth_requirement={provider_type:"oauth2", provider_id:"google", oauth2:{scopes}}, user_id=...)` (`server.py:1964-2020`). It uses `ARCADE_API_KEY` from env, falling back to `arcade login` credentials (`server.py:496-540`). The `user_id` comes from `ARCADE_USER_ID`, falling back to the `arcade login` email and then the session id (`server.py:1163-1202`). Setting `ARCADE_API_KEY` + `ARCADE_USER_ID=$BUTLER_USER_ID` reuses Butler's grant. No `arcade login` is needed.
  - In-process: `client.auth.start(BUTLER_USER_ID, "google", scopes)` returns `status=="completed"` with a token when the grant already exists (pattern from `call-third-party-apis` and `resources/faq` "broader OAuth scopes").
- Pitfall: if the custom tool asks for a scope Butler hasn't granted yet, Arcade returns an auth URL instead of a token. Fix: `scripts/authorize.py` requests the union of catalog and custom scopes once (FAQ shows `auth.start` with multiple scopes). If the tool is deployed, `client.tools.authorize(tool_name="ButlerTools.X", user_id=...)` also works.
- This is not a new constraint, because it already applies to catalog calls (D1). Default Arcade OAuth apps only work with the Arcade user verifier, which "asks the end-user to sign in to an Arcade Cloud account that is a member of the project" (`resources/security-research-program`, `build/user-facing-agents/secure-auth-production`).

## 3. Minimal scaffold and commands

```bash
uv tool install arcade-mcp          # CLI "arcade" (PyPI arcade-mcp 1.16.1)
arcade new butler_tools             # minimal scaffold
# butler_tools/
#   .env.example
#   pyproject.toml                  # deps: arcade-mcp-server, httpx; entry-point arcade_toolkits
#   src/butler_tools/{__init__.py, server.py}
cd butler_tools && uv sync
uv run src/butler_tools/server.py stdio   # local, auth works (single user)
uv run src/butler_tools/server.py http    # local http on :8000; auth tools blocked unless ARCADE_WORKER_SECRET + registered
arcade login                              # browser OAuth to Arcade (needed for deploy)
arcade deploy -e src/butler_tools/server.py   # run from dir containing pyproject.toml
arcade server list | logs                 # manage deployed servers
```
Sources: `build/create-tools/tool-basics/build-mcp-server`, `build/arcade-deploy`, CLI `libs/arcade-cli/arcade_cli/main.py` (`new` ~430, `mcp` 463, `deploy` 1109, `server` subcommands in `server.py:145-245`), template `libs/arcade-cli/arcade_cli/templates/minimal/`.

Minimal tool:
```python
from typing import Annotated
from arcade_mcp_server import Context, MCPApp
from arcade_mcp_server.auth import Google

app = MCPApp(name="butler_tools", version="0.1.0")

@app.tool(requires_auth=Google(scopes=["https://www.googleapis.com/auth/calendar.events"]))
async def add_attendee(context: Context, event_id: Annotated[str, "..."], email: Annotated[str, "..."]) -> dict:
    """Add an attendee to a Butler calendar event and send Google's invite."""
    return await calendar_add_attendee(context.get_auth_token_or_empty(), event_id, email)

if __name__ == "__main__":
    import sys
    app.run(transport=sys.argv[1] if len(sys.argv) > 1 else "stdio")
```
For deploy, the entrypoint must call `app.run()` under `if __name__ == "__main__"` (`build/arcade-deploy`).

### What `arcade deploy` actually does (`libs/arcade-cli/arcade_cli/deploy.py:821-990`)
1. Checks login (`arcade login` config). Alternatively, if both `ARCADE_URL` and `ARCADE_API_KEY` are set in the shell, it uses "CI" mode with the API key (`deploy.py:853-856`, `context.py:142-157`). The docs only document `ARCADE_URL` for `arcade login`, so the CI path is code-only and **unverified** live.
2. Requires `pyproject.toml` in cwd and the entrypoint file.
3. Loads `.env`, **starts the server locally** to health-check it, then reads its name, version, and required secrets. The reviewer therefore needs the deps installed locally; `--skip-validate --server-name --server-version` skips this.
4. Uploads the required secrets, tars the directory (excluding dotfiles, `__pycache__`, `dist`, `build`, and `*.lock`; `deploy.py:366-410`), then POSTs `/deployments` or PUTs on update.
5. Streams status until the server is "running". The docs say "this may take a few minutes".
- Deployments belong to the logged-in **org/project** (`get_org_scoped_url`, `utils.py`). The reviewer has to deploy into the **same project as the `ARCADE_API_KEY`** in `.env`. A server deployed in our project is invisible to the reviewer's key.
- Every change to the tool code needs a redeploy.

## 4. Reviewer friction per option

| Option | `tools.execute`? | Reviewer extra steps (beyond clone, `.env`, `authorize.py`, run) | Lost vs. Arcade-routed |
|---|---|---|---|
| **D in-process** (call tool fn; token via `client.auth.start`) | no (direct call) | **none** | Custom calls don't go through the Engine: no execution log/audit for them in the dashboard, not in the project catalog/gateways, not callable from other MCP clients, no MCP protocol boundary. Google token still comes from Arcade's vault. |
| **C local stdio subprocess** (app spawns `server.py stdio`, talks MCP via `mcp` SDK client; env `ARCADE_API_KEY`, `ARCADE_USER_ID`) | no | **none** (process spawned by app) | Same as D minus "no MCP boundary". Adds a subprocess, an `mcp` client dependency, and a second transport inside `gateway.py`. |
| **A `arcade deploy`** | **yes** | install CLI (`uv tool install arcade-mcp`), `arcade login` (browser; pick same project as API key), `arcade deploy -e …` (minutes), redeploy on change | nothing; full Arcade path (catalog, dashboard logs, gateways). Free-plan limits on hosted servers are **not stated** on arcade.dev/pricing (it lists only 2,000 auth events + 2,000 tool calls/month). |
| **B hybrid worker + tunnel** | **yes** | install tunnel tool, set `ARCADE_WORKER_SECRET`, run `server.py http`, start tunnel, register URL in dashboard (or `client.workers.create`, perms unverified), re-register on every restart (ephemeral URL), keep 3 processes up | nothing functionally; fragile. |

## 5. Recommendation

Lowest friction for a clone-and-run repo: **D (in-process)**.
- Write the custom tool as a real arcade-mcp tool (`@app.tool(requires_auth=Google(...))` in `tools/`), so it can be deployed and the writeup can argue catalog vs. custom honestly. Put the Google API call in a plain function.
- In the app, `gateway.py` calls that function with Butler's token from `client.auth.start(BUTLER_USER_ID, "google", SCOPES)`. `scripts/authorize.py` requests the union of scopes once, so nothing new is asked at runtime.
- Document `arcade deploy` as optional: "to run the custom tool through Arcade's Engine instead, `arcade deploy` and set `CUSTOM_TOOL_RUNTIME=arcade`". Only add that switch if it costs nothing; otherwise just mention it in the WRITEUP as the production path.
- If an MCP boundary matters for the story, C costs the reviewer nothing more but adds code.

Before building any of this, the catalog check below suggests the custom tool may be unnecessary.

## Catalog check (flag for tickets 01/06)

From docs repo `toolkit-docs-generator/data/toolkits/` (catalog snapshot, not a live call):
- `GoogleCalendar.UpdateEvent` params: `event_id, updated_start_datetime, updated_end_datetime, updated_calendar_id, updated_summary, updated_description, updated_location, updated_visibility, updated_recurrence, attendee_emails_to_add, attendee_emails_to_remove, send_notifications_to_attendees, updated_google_meet`.
- `GoogleCalendar.CreateEvent` params include `attendee_emails, send_notifications_to_attendees`.
- `Gmail.ReplyToEmail` params: `body, reply_to_message_id, reply_to_whom, cc, bcc, content_type, attachments`.
- `Gmail.SendEmail` params: `subject, body, recipient, cc, bcc, content_type, attachments`.

The semantics still need ticket 01's source read and ticket 05's live check: whether `reply_to_whom` supports reply-all, whether `cc` adds recipients in the same thread, and what `send_notifications_to_attendees` maps to in `sendUpdates`.

## Unverified / for live check
- `client.workers.create` with a project API key (Admin-tagged endpoint).
- `arcade deploy` CI mode (`ARCADE_URL` + `ARCADE_API_KEY`, no browser login).
- Whether the free plan allows Arcade Deploy (the reviewer uses their own account; the PDF's "unlimited credits" applies to the candidate).
- `client.auth.start` returning `completed` immediately for a subset of already-granted scopes. The docs imply it; confirm with one call.
