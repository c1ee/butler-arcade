"""Live evals: `uv run pytest evals` (on demand, not in CI). Needs ANTHROPIC_API_KEY (environment or .env).

Every selected Eval case runs --runs times (default 3) against live Claude, in parallel, before the family tests
check their pass bars. The table and failures print at the end; a full run (no --case) also writes evals/RESULTS.md.
Full traces of each Run go to evals/traces/ (gitignored).
"""

import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import anthropic
import pytest

from butler import config
from butler.config import Settings
from evals import harness, report
from evals.cases import CASES
from tests.fakes import BUTLER, HOST

HERE = Path(__file__).parent
RESULTS: list[harness.Result] = []
META: dict[str, str] = {}


def pytest_addoption(parser):
    group = parser.getgroup("evals")
    group.addoption("--runs", type=int, default=3, help="Runs per Eval case (default 3; 1 when iterating)")
    group.addoption("--case", action="append", default=[], help="only cases whose id contains this (repeatable)")
    group.addoption("--workers", type=int, default=8, help="Runs in parallel (default 8)")


def pytest_collection_modifyitems(items):
    config.read_env_file()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        skip = pytest.mark.skip(reason="live evals need ANTHROPIC_API_KEY")
        for item in items:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def results(request):
    options = request.config.option
    cases = [case for case in CASES if not options.case or any(part in case.id for part in options.case)]
    settings = Settings(arcade_api_key="", anthropic_api_key=os.environ["ANTHROPIC_API_KEY"], butler_user_id=BUTLER,
                        host_email=HOST, model=os.environ.get("MODEL") or config.DEFAULT_MODEL)
    claude = anthropic.Anthropic(api_key=settings.anthropic_api_key, max_retries=8)
    stamp = datetime.now().astimezone()
    traces = HERE / "traces" / f"{stamp:%Y%m%d-%H%M%S}"
    traces.mkdir(parents=True)
    terminal = request.config.pluginmanager.get_plugin("terminalreporter")
    terminal.write_line(f"\n{len(cases)} cases × {options.runs} Runs on {settings.model}, {options.workers} at a time")

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=options.workers) as pool:
        futures = [pool.submit(harness.run, case, claude, settings, number, traces)
                   for case in cases for number in range(1, options.runs + 1)]
        for future in futures:
            result = future.result()
            RESULTS.append(result)
            terminal.write("E" if result.error else "L" if result.leaks else "." if result.passed else "F")
    terminal.write_line("")
    minutes, seconds = divmod(round(time.monotonic() - started), 60)
    META.update({
        "Date": f"{stamp:%Y-%m-%d %H:%M %Z}",
        "Model": settings.model,
        "Commit": commit(),
        "Cases": f"{len(cases)} ({options.runs} Runs each, {len(RESULTS)} Runs)",
        "Wall time": f"{minutes}m {seconds:02d}s",
        "Traces": f"evals/traces/{traces.name}/ (not committed)",
    })
    META["full"] = "" if options.case else "yes"
    return RESULTS


def commit() -> str:
    def git(*args):
        return subprocess.run(["git", *args], cwd=HERE, capture_output=True, text=True, check=False).stdout.strip()

    sha = git("rev-parse", "--short", "HEAD") or "unknown"
    changed = git("status", "--porcelain", "--", "butler", "evals", "tests", ":!evals/RESULTS.md")
    return f"{sha} + uncommitted changes" if changed else sha


def pytest_terminal_summary(terminalreporter):
    if not RESULTS:
        return
    full = META.pop("full", "")
    text = report.markdown(RESULTS, META)
    terminalreporter.write_sep("=", "eval results")
    terminalreporter.write_line(text)
    if full:
        (HERE / "RESULTS.md").write_text(text)
        terminalreporter.write_line("Wrote evals/RESULTS.md")
