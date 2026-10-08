"""Live-check helpers: env, Arcade client, logged tool calls, shared state."""
import json, os, pathlib, time

HERE = pathlib.Path(__file__).parent
ENV = {}
for line in (HERE.parent / ".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        ENV[k.strip()] = v.strip()

from arcadepy import Arcade

client = Arcade(api_key=ENV["ARCADE_API_KEY"])
BUTLER = ENV["BUTLER_USER_ID"]
HOST, A, B, C = ENV["HOST_EMAIL"], ENV["GUEST_A"], ENV["GUEST_B"], ENV["GUEST_C"]
SCOPES = [
    "https://www.googleapis.com/auth/" + s
    for s in ["gmail.send", "gmail.readonly", "calendar.events", "calendar.readonly", "calendar.settings.readonly"]
]
MS_SCOPES = ["Mail.Read", "Mail.Send", "User.Read"]
STATE = HERE / "state.json"
LOG = HERE / "log.jsonl"


def run(tool, as_=None, **inputs):
    r = client.tools.execute(tool_name=tool, input=inputs, user_id=as_ or BUTLER)
    out = r.output
    rec = {"t": time.strftime("%H:%M:%S"), "as": as_ or BUTLER, "tool": tool, "input": inputs,
           "value": getattr(out, "value", None), "error": (out.error.model_dump() if out and out.error else None)}
    with LOG.open("a") as f:
        f.write(json.dumps(rec, default=str) + "\n")
    if rec["error"]:
        print(f"!! {tool} error: {rec['error']}")
    return rec["value"]


def load():
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def save(s):
    STATE.write_text(json.dumps(s, indent=2, default=str))
