# arcade evals fit for domain tools

Type: research
Mode: AFK
Status: resolved

## Question

Can `arcade evals` score our own in-process domain tools (e.g. `record_rsvp`, `change_event`) with a Claude model, without deploying them?
- How are tools registered in an `EvalSuite` catalog: arcade-mcp `@tool` functions, raw JSON schemas, or MCP servers?
- Anthropic model support (provider flag, model id)?
- Can one case expect multiple tool calls (e.g. `record_rsvp` + `get_event`)? Can it assert a tool was NOT called?
- Can it check the final reply text (needed for leak evals), or only tool calls?
- Install + run command, and what output/report looks like.
Conclude: usable for tool-call evals (yes/no/partial), and what plain pytest must cover instead.

## Answer

**Verdict: partial.** It works for single-response tool-call evals. It can't do leak evals or anything else that needs the reply text or the real tool loop.

- **Registering tools:** `suite.add_tool_definitions([{name, description, inputSchema}])` takes raw JSON schemas, so we can reuse the schemas from `tools.py`. No `@tool` decorator, MCP server or deploy is needed. The other options are `ToolCatalog`, `add_mcp_server`, `add_mcp_stdio_server` and `add_arcade_gateway`. Tools are set per suite, so we need one `@tool_eval` suite per toolset (role × channel × phase).
- **Anthropic:** `arcade evals <dir> -p anthropic:<model-id>` with `ANTHROPIC_API_KEY`. No `arcade login` needed. Without `-p` it falls back to OpenAI `gpt-4o`. The request is fixed at `max_tokens=4096`, with no temperature, thinking or tool_choice, and `--seed` is ignored. Use `-n 3 --multi-run-pass-rule majority`.
- **Multiple calls:** yes, matched regardless of order. But only `tool_use` blocks from the **first and only** model response count; tools are never run and there's no loop.
- **NOT called:** only indirectly. By default the rubric requires the exact count and names of tool calls, so an unexpected extra call fails the case, and `expected_tool_calls=[]` means "no tools". There's no "must not call X" option.
- **Reply text:** never checked. Text blocks are thrown away.
- **Install / run:** `pip install 'arcade-mcp[evals]'` (1.16.1; there's no separate `arcade-evals` package). It pins `arcadepy==1.8.0`, `openai==1.82.1` and `mcp<2`. Run with `arcade evals evals/ -p anthropic:<model> -d -o results.json`. Reports come as txt, md, html or json. **The exit code is always 0**, so CI has to check `summary.failed` in the JSON, or call `suite.run()` from pytest.
- **Plain pytest must cover:** all leak evals, `should_speak` and `catch_up_summary`, loop behavior (calls that happen in sequence, "asks for missing", use of tool results, the iteration cap), the real `agent.py` request parameters, CI gating, and all deterministic tests.
- **Recommendation:** one pytest harness that runs the real `agent.py` with a fake gateway and records tool calls and final text covers both tool-call and leak evals. arcade evals is optional, worth adding only if being Arcade-native matters.
- I verified this end to end by running the CLI against a mock Anthropic endpoint: a multi-call case passed, an extra-call case failed, and a no-tool case passed even though its reply leaked private text. Exit code was 0.
- Full findings, with line-pinned source citations and an eval file sketch: [research/arcade-evals-fit.md](../research/arcade-evals-fit.md)
- Time: ~5 min wall-clock.
