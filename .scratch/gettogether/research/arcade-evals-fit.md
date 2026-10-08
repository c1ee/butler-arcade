# arcade evals: does it fit our in-process domain tools?

Ticket: `../issues/02-arcade-evals-fit.md`. Researched 2026-10-05.

**Verdict: partial.** `arcade evals` scores our own domain tools with Claude, locally, with no deploy and no Arcade login. You register the tools as raw JSON schemas; no `@tool` decorator or MCP server is needed. But it only scores **tool calls from one model response**. It never runs the tools, never loops, and never looks at the reply text. It also always exits with code 0.

## Sources and versions

- PyPI: there is **no `arcade-evals` package** (PyPI returns 404 for that name). Evals ship inside **`arcade-mcp` 1.16.1** (released 2026-09-25) as the `[evals]` extra. Installed the same way the docs say: `pip install 'arcade-mcp[evals]'`. This pulled in `arcade-core 4.22.0`, `arcade-tdk 3.15.0`, `arcadepy 1.8.0`, `anthropic 1.11.0`, `openai 1.82.1`, `mcp 1.30.0`, numpy, scipy and scikit-learn. The install worked on Python 3.14.
  - Note: `arcade-cli` on PyPI (0.3.2) is an **unrelated** project.
- Source: https://github.com/ArcadeAI/arcade-mcp at commit `78e9820938dc7f796a5c4cd0ea73d2cbe2c682d9` (main, 2026-10-02). Evals code is in `libs/arcade-evals/arcade_evals/`; the CLI is in `libs/arcade-cli/arcade_cli/`. I diffed this against the 1.16.1 wheel and the files are byte-identical, so the line numbers below hold for both. Short form used below: `GH/<path>#L..` = `https://github.com/ArcadeAI/arcade-mcp/blob/78e9820938dc7f796a5c4cd0ea73d2cbe2c682d9/libs/<path>#L..`. Bare names like `eval.py`, `_types.py`, `_convenience.py`, `_tool_registry.py`, `_providers.py`, `critic.py` and `capture.py` are under `libs/arcade-evals/arcade_evals/` (or its `_evalsuite/` subfolder). `main.py`, `utils.py`, `evals_runner.py`, `formatters/` and `usage/` are under `libs/arcade-cli/arcade_cli/`. `pyproject.toml` is the file at the repo root.
- Docs:
  - https://docs.arcade.dev/en/build/create-tools/evaluate-tools/create-evaluation-suite
  - https://docs.arcade.dev/en/build/create-tools/evaluate-tools/run-evaluations
  - https://docs.arcade.dev/en/build/create-tools/evaluate-tools/comparative-evaluations
  - https://docs.arcade.dev/en/build/create-tools/evaluate-tools/why-evaluate
  - The docs have no separate critics page. The critics are listed in a table on the create-evaluation-suite page.
- `libs/arcade-evals/README.md` is **stale**. Its examples use `EvalCase(input=..., expected_output=...)` and `@tool_eval(suite)`, which don't match the code. Ignore it.
- **I ran it.** I wrote a sample suite and ran `arcade evals` against a local mock of the Anthropic Messages API (via `ANTHROPIC_BASE_URL`). The mock logged what the client sent and returned canned `tool_use` blocks. Results are under "Verified run" below.

## Answers

### 1. How tools get into the suite's catalog

There are five ways. Every tool ends up in one internal registry stored in MCP shape: `{name, description, inputSchema}` (`GH/arcade-evals/arcade_evals/_evalsuite/_tool_registry.py#L41-L95`).

| Method | Source | Expectation type |
|---|---|---|
| `EvalSuite(catalog=ToolCatalog)` or `suite.add_tool_catalog(catalog)`, using functions decorated with arcade-tdk `@tool` | `eval.py#L506-L556`, `_convenience.py#L216-L233` | `ExpectedToolCall(func, args)` (`_types.py#L51-L68`) |
| **`suite.add_tool_definitions([{"name","description","inputSchema"}])`**: raw JSON Schema | `_convenience.py#L72-L107` | `ExpectedMCPToolCall("name", args)` (`_types.py#L71-L91`) |
| `await suite.add_mcp_server(url, headers=, use_sse=)`: MCP over HTTP | `_convenience.py#L109-L140` | `ExpectedMCPToolCall` |
| `await suite.add_mcp_stdio_server(command=[...])`: MCP over stdio | `_convenience.py#L142-L171` | `ExpectedMCPToolCall` |
| `await suite.add_arcade_gateway(slug)`: Arcade cloud gateway | `_convenience.py#L173-L214` | `ExpectedMCPToolCall` |

**For us: use `add_tool_definitions`.** We can feed it the same JSON schemas `tools.py` already passes to `messages.create`, with the key `input_schema` renamed to `inputSchema`.
- For Anthropic, the schema is passed through almost unchanged: `inputSchema` becomes `input_schema`, and dots in names become underscores (`_anthropic_schema.py#L19-L44`, `_tool_registry.py#L162-L180`).
- Snake_case names like `record_rsvp` are unaffected.
- Names are compared case-insensitively, treating `-`, `_` and `.` as the same (`eval.py#L1196-L1222`).
- Tool names must be unique across the whole suite (`_tool_registry.py#L90-L94`).
- The tool list is set per suite, not per case. Our toolsets differ by role × channel × phase, so we need **one `@tool_eval` suite per toolset**. The CLI collects every `@tool_eval` function in every `eval_*.py` file (`GH/arcade-cli/arcade_cli/utils.py#L879-L993`).

### 2. Anthropic support

- `ProviderName = Literal["openai", "anthropic"]` (`_providers.py#L21`).
- CLI flags:
  - `-p/--use-provider anthropic[:model1,model2]`.
  - The default Anthropic model is `claude-sonnet-4-5-20250929` (`utils.py#L82-L85`). Any model ID string is passed straight through.
  - Without `-p`, the CLI uses **OpenAI `gpt-4o`** and errors if `OPENAI_API_KEY` is missing (`main.py#L785-L803`). So always pass `-p anthropic:<model>`.
- API key comes from `-k anthropic:KEY`, then the `ANTHROPIC_API_KEY` environment variable, then a `.env` file in the current directory (`utils.py#L315-L362`).
- The request is fixed (`eval.py#L1105-L1148`): `client.messages.create(model, max_tokens=4096, system=case.system_message, messages, tools)`.
  - It sends no `temperature`, `tool_choice`, thinking or caching settings.
  - `--seed` is **ignored** for Anthropic (`eval.py#L877-L887`).
  - Because temperature isn't set, results vary run to run. Use `--num-runs N --multi-run-pass-rule majority|mean` (`main.py#L644-L660`, `eval.py#L164-L191`).
- `evals` is in the CLI's `public_commands`, so **no `arcade login`** is needed (`main.py#L1388-L1402`).

### 3. Multiple calls, and asserting a tool was NOT called

- **Multiple calls: yes.** `expected_tool_calls` is a list. Expected calls are matched to actual calls with the Hungarian algorithm (scipy `linear_sum_assignment`), so order doesn't matter (`eval.py#L348-L399`, `#L412-L460`).
  - **Catch:** only `tool_use` blocks from the **first and only** assistant response count (`eval.py#L1143-L1146`). Claude has to emit `record_rsvp` and `get_event` as parallel calls in that one response.
  - If Claude calls `get_event`, waits for the result, and then calls `record_rsvp`, the eval sees only the first call and the case fails.
- **Negative assertion: only indirectly.** There's no "must not call X" option. Instead, `EvalRubric` defaults to `fail_on_tool_call_quantity=True` and `fail_on_tool_selection=True` (`_types.py#L112-L129`). Together these require the actual calls to match the expected calls exactly, in both count and names (`eval.py#L270-L298`, `#L318-L341`).
  - So `expected=[escalate_to_host]` fails if the model also calls `record_rsvp`. I verified this.
  - `expected_tool_calls=[]` passes only if no tool is called (`eval.py#L331-L334`).
  - Pitfall 1: if you set `fail_on_tool_call_quantity=False`, extra calls go unnoticed. The name check zips two sorted lists, which drops the extras, and scoring only looks at matched pairs (`eval.py#L280-L285`, `#L357-L402`).
  - Pitfall 2: there's no way to say "X must not be called, but other calls can vary".
- Argument checks use critics, one per argument name per case (`eval.py#L700-L718`):
  - `BinaryCritic`: exact match after casting the actual value to the expected type (`critic.py#L68`).
  - `NumericCritic` (`critic.py#L137`).
  - `SimilarityCritic`: TF-IDF cosine similarity (`critic.py#L190`).
  - `DatetimeCritic`: tolerance window (`critic.py#L293`).
  - Arguments in the expected call that have no critic get a zero-weight `NoneCritic` (`eval.py#L672-L698`). Arguments the model adds that aren't in the expected call are ignored.

### 4. Can it check the final reply text?

**No.** Both scoring and capture read only `tool_use` blocks. Text blocks are thrown away (`eval.py#L1143-L1146`). Captured results hold only `{name, args}` (`capture.py#L23-L54`).
- The docs say the same thing: "Tool selection" and "Parameter accuracy" (why-evaluate), and comparative evals only cover tool choice and argument accuracy.
- **Leak evals can't be done with this.** In the verified run, a case whose reply leaked "the surprise for Bob" still **PASSED**.

### 5. Install, run, and report format

```bash
pip install 'arcade-mcp[evals]'          # or: uv tool install 'arcade-mcp[evals]'
export ANTHROPIC_API_KEY=...
ARCADE_USAGE_TRACKING=0 arcade evals evals/ -p anthropic:claude-sonnet-4-6 --details -o results.json
```

- **File discovery:** the CLI searches the directory recursively for `eval_*.py` files (skipping venv, `.git` and similar). It imports each one with **only the file's own directory** added to `sys.path` (`utils.py#L879-L993`). So `import butler.tools` needs `pip install -e .` or `PYTHONPATH=.`.
- **Flags:**
  - `-d/--details`: per-critic results.
  - `-f/--only-failed`.
  - `-c` concurrency.
  - `-n/--num-runs`.
  - `--multi-run-pass-rule last|mean|majority`.
  - `--capture`: record tool calls without scoring.
  - `--include-context`.
  - `-o FILE`, repeatable. The format comes from the file extension: `txt`, `md`, `html` or `json`. With no extension, all four are written (`main.py#L634-L709`, `evals_runner.py#L31`).
- **Thresholds:** a case passes at score ≥ `fail_threshold` (default 0.8). Between `warn_threshold` (0.9) and `fail_threshold`, it's a warning (`eval.py#L404-L408`).
- **Exit code is always 0**, even when cases fail. `run_evaluations` prints results and returns without setting an exit status (`evals_runner.py#L250-L381`). I verified this: one case failed and the exit code was 0.
  - For a CI gate, parse `results.json` and check `.summary.failed`, or call `await suite.run(AsyncAnthropic(), model, provider="anthropic")` from pytest and assert on `case["evaluation"].passed`. I verified the pytest route too.
- **Telemetry:** the CLI sends usage data unless `ARCADE_USAGE_TRACKING=0` (`usage/command_tracker.py#L254`).
- **Dependency pins** (`pyproject.toml#L28,#L39,#L53`):
  - `arcadepy==1.8.0` (latest is 1.10.0).
  - `openai==1.82.1`. `eval.py` imports openai unconditionally, so it's needed even for Anthropic-only runs.
  - `mcp<2` (latest is 2.3.0).
  - If the app and the evals share one environment, our arcadepy gets pinned to 1.8.0.

### Verified run (mock Anthropic API, `-p anthropic:claude-sonnet-4-6`)

The request the eval client sent, as logged by the mock:

```
{max_tokens: 4096, model: claude-sonnet-4-6, system: <suite system>, messages: [{role: user, content: "yes! what's parking like?"}],
 tools: [get_event, get_my_rsvp, record_rsvp, escalate_to_host]}   # input_schema passed through unchanged
```

Text report:

```
PASSED yes + parking -> record_rsvp + get_event -- Score: 100.00%
FAILED dog -> escalate only (no record_rsvp) -- Score: 0.00%
  Failure Reason: Expected 1 tool call(s), but got 2. Actual tool calls: escalate_to_host, record_rsvp
PASSED thanks -> no tool calls -- Score: 100.00%      # reply text leaked "surprise for Bob"; not checked
Summary -- Total: 3 -- Passed: 2 -- Failed: 1
EXIT=0
```

JSON report: `{type: "evaluation", generated_at, summary: {total_cases, passed, failed, warned, pass_rate}, models: {<model>: {suites: {<suite>: {case_count, cases: [{name, input, status, score, passed, warning, failure_reason, ...}]}}}}}` (`formatters/json.py#L85-L121`).

## Minimal eval file sketch (the case the ticket asked for)

```python
# evals/eval_guest_private.py   (run: PYTHONPATH=. arcade evals evals -p anthropic:<MODEL>)
from arcade_evals import BinaryCritic, EvalRubric, EvalSuite, ExpectedMCPToolCall, tool_eval
from butler.tools import toolset, tool_schemas        # same schemas agent.py sends
from butler.agent import system_prompt                # same prompt builder agent.py uses
from tests.fixtures import event_fixture              # state fixture rendered into the prompt

def as_mcp(schemas):  # Anthropic tool dict -> MCP-style descriptor
    return [{"name": s["name"], "description": s["description"], "inputSchema": s["input_schema"]} for s in schemas]

@tool_eval()
def guest_private_suite() -> EvalSuite:
    suite = EvalSuite(
        name="guest/private",
        system_message=system_prompt(role="guest", channel="private", event=event_fixture()),
        rubric=EvalRubric(fail_threshold=0.9),   # exact count + names are enforced by default
    )
    suite.add_tool_definitions(as_mcp(tool_schemas(toolset("guest", "private", "approved"))))
    suite.add_case(
        name="yes + parking -> record_rsvp + get_event",
        user_message="yes! what's parking like?",
        expected_tool_calls=[
            ExpectedMCPToolCall("record_rsvp", {"attending": True}),
            ExpectedMCPToolCall("get_event", {}),
        ],
        critics=[BinaryCritic(critic_field="attending", weight=1.0)],
    )
    suite.add_case(  # "NOT called" = exact-set match; record_rsvp here fails the case
        name="dog -> escalate only",
        user_message="can I bring my dog?",
        expected_tool_calls=[ExpectedMCPToolCall("escalate_to_host", {})],
    )
    return suite
```

A version of this with the schemas written inline instead of imported from `butler` was run and verified (output above). The `butler.*` imports are placeholders for the planned modules. A case can also include earlier turns via `additional_messages`, written in OpenAI chat format. That includes fake assistant `tool_calls` and `tool` result messages, which the suite converts to Anthropic `tool_use` and `tool_result` blocks (`_providers.py#L24-L151`). This lets a case represent a later turn of a conversation, but you have to write those earlier turns by hand.

## What plain pytest must cover instead

1. **Leak evals (all of them).** They need the final reply text, which arcade evals throws away.
2. **`should_speak` and `catch_up_summary`.** These are structured-output calls, not tool calls.
3. **Anything that depends on the loop:**
   - "host partial setup → `update_draft` + **asks for missing**": the "asks" part is reply text.
   - Calls that come one after another, e.g. `get_event`, then a reply using its result.
   - The iteration cap.
   - Whether the reply actually used the tool results (e.g. parking info from `get_event`).

   arcade evals never runs our `agent.py` loop, `gateway.py` or the tools themselves.
4. **Request parameters that differ from the eval's fixed request** (`max_tokens=4096`, no temperature/thinking/tool_choice). Those settings in `agent.py` are only exercised by a harness that calls `agent.py`.
5. **CI gating** (the CLI always exits 0) and all deterministic tests: the toolset matrix, outbox, idempotency, threshold, lifecycle.

**Practical implication:** a pytest harness that runs the real `agent.py` loop with a fake gateway against Claude, and records `(tool calls, final text)`, covers tool-call evals *and* leak evals in one place. arcade evals would be a second harness that tests a simplified single-turn version of the agent, not the real loop. It's worth adding only if being Arcade-native matters (e.g. for the reviewer). If so, keep it to the ~20 first-turn tool-selection cases, gate CI on `results.json`, and run it with `-n 3 --multi-run-pass-rule majority`.
