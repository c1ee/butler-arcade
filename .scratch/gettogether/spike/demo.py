"""Ticket 17 dry run: drive the demo script as Host/A/B through Arcade while `POLL_SECONDS=10 uv run butler` runs.

Run from projects/gettogether: `uv run python ../pstack/.scratch/gettogether/spike/demo.py <step> ...`
Steps: `host <text>` Host fresh email · `hostreply <text>` Host replies in the Host thread ·
`reply <who> <text>` reply to Butler's latest private email to that account · `all <who> <text>` reply-all in the Group
thread · `inbox <who> [n]` · `event` Butler's event · `cal <who>` that account's calendar on 10/17 ·
`cleanup` silently delete the db's events.
"""
import json
import sqlite3
import sys
import time

from lc import A, B, BUTLER, C, HOST, run

WHO = {"host": HOST, "a": A, "b": B, "c": C}
DB = "/Users/sang/chrislee/projects/gettogether/butler.db"
SUBJECT = "Dinner Saturday"
GROUP = 'subject:"Everyone coming"'


def latest_from_butler(account, n=5, query=""):
    value = run("Gmail.SearchEmailsByQuery", as_=account, query=f"from:{BUTLER} newer_than:3h {query}", max_results=n,
                result_detail="full")
    return value["emails"]


def stamp(what):
    print(time.strftime("%H:%M:%S"), "sent:", what)


step = sys.argv[1]
if step == "host":
    run("Gmail.SendEmail", as_=HOST, recipient=BUTLER, subject=SUBJECT, body=sys.argv[2])
    stamp("host fresh")
elif step == "hostreply":
    mid = latest_from_butler(HOST, 1, f"-{GROUP}")[0]["message_id"]
    run("Gmail.ReplyToEmail", as_=HOST, reply_to_message_id=mid, reply_to_whom="only_the_sender", body=sys.argv[2])
    stamp("host reply")
elif step == "reply":
    mid = latest_from_butler(WHO[sys.argv[2]], 1, f"-{GROUP}")[0]["message_id"]
    run("Gmail.ReplyToEmail", as_=WHO[sys.argv[2]], reply_to_message_id=mid, reply_to_whom="only_the_sender",
        body=sys.argv[3])
    stamp(f"{sys.argv[2]} reply")
elif step == "all":
    mid = latest_from_butler(WHO[sys.argv[2]], 1, GROUP)[0]["message_id"]
    run("Gmail.ReplyToEmail", as_=WHO[sys.argv[2]], reply_to_message_id=mid, reply_to_whom="every_recipient",
        body=sys.argv[3])
    stamp(f"{sys.argv[2]} reply-all")
elif step == "inbox":
    for e in latest_from_butler(WHO[sys.argv[2]], int(sys.argv[3]) if len(sys.argv) > 3 else 5):
        print("=" * 70, "\n", e["date"], "|", e["subject"], "| from:", e.get("from"), "| to:", e["to"], "| cc:",
              e["cc"])
        print(e["body"][:1500])
elif step == "event":
    event_id = sqlite3.connect(DB).execute("SELECT calendar_event_id FROM dinner ORDER BY id DESC").fetchone()[0]
    value = run("GoogleCalendar.GetEvent", event_id=event_id)
    print(json.dumps({k: value.get(k) for k in ("status", "start", "location", "description", "attendees")},
                     indent=1) if value else value)
elif step == "cal":
    value = run("GoogleCalendar.ListEvents", as_=WHO[sys.argv[2]], min_end_datetime="2026-10-17T00:00:00",
                max_start_datetime="2026-10-18T00:00:00")
    for e in (value or {}).get("events", []):
        print(e.get("id"), e.get("status"), e.get("summary"), e.get("start"))
    print("events:", len((value or {}).get("events", [])))
elif step == "cleanup":
    for (event_id,) in sqlite3.connect(DB).execute("SELECT calendar_event_id FROM dinner WHERE calendar_event_id IS "
                                                   "NOT NULL"):
        print(event_id, run("GoogleCalendar.DeleteEvent", event_id=event_id, send_updates="nobody"))
