"""Ticket 13 live check: Host writes, Changes, cancel (run tag hw1). Threshold 1 so A starts the Group thread; B stays
Invited; C (Outlook) is invited after launch.

Steps: `butler` run Butler (db /tmp/butler_hw1.db, poll 15s) · `host <text>` Host fresh email ·
`hostreply <text>` Host replies in the Host thread · `hostall <text>` Host reply-all in the Group thread ·
`reply <who> <text>` reply to Butler's latest email to that account, to Butler only · `inbox <who> [n]` ·
`event` Butler's event · `cal <who>` that account's calendar on 10/24.
"""
import json
import sqlite3
import sys
import time

from lc import A, B, BUTLER, C, HOST, run

WHO = {"host": HOST, "a": A, "b": B, "c": C}
DB = "/tmp/butler_hw1.db"
SUBJECT = "hw1 dinner"


def latest_from_butler(account, n=5, query=""):
    value = run("Gmail.SearchEmailsByQuery", as_=account, query=f"from:{BUTLER} newer_than:1h {query}", max_results=n,
                result_detail="full")
    return value["emails"]


def event_id():
    return sqlite3.connect(DB).execute("SELECT calendar_event_id FROM dinner ORDER BY id DESC").fetchone()[0]


step = sys.argv[1]
if step == "butler":
    import logging
    from dataclasses import replace
    from datetime import UTC, datetime

    import anthropic

    from butler import config
    from butler.gateway import Gateway
    from butler.main import poll_once, tick
    from butler.store import Store

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    for noisy in ("httpx", "httpx2"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    settings = replace(config.load(), db_path=DB)
    store, gateway = Store(settings.db_path), Gateway(settings)
    claude = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    while True:
        now = datetime.now(UTC)
        try:
            poll_once(gateway, claude, store, settings, now)
            tick(gateway, store, settings, now)
        except Exception:
            logging.exception("poll failed")
        time.sleep(15)
elif step == "host":
    run("Gmail.SendEmail", as_=HOST, recipient=BUTLER, subject=SUBJECT, body=sys.argv[2])
elif step == "hostreply":
    mid = latest_from_butler(HOST, 1, f'subject:"{SUBJECT}"')[0]["message_id"]
    print(run("Gmail.ReplyToEmail", as_=HOST, reply_to_message_id=mid, reply_to_whom="only_the_sender",
              body=sys.argv[2]))
elif step == "hostall":
    mid = latest_from_butler(HOST, 1, 'subject:"Group thread"')[0]["message_id"]
    print(run("Gmail.ReplyToEmail", as_=HOST, reply_to_message_id=mid, reply_to_whom="every_recipient",
              body=sys.argv[2]))
elif step == "reply":
    mid = latest_from_butler(WHO[sys.argv[2]], 1)[0]["message_id"]
    print(run("Gmail.ReplyToEmail", as_=WHO[sys.argv[2]], reply_to_message_id=mid, reply_to_whom="only_the_sender",
              body=sys.argv[3]))
elif step == "inbox":
    for e in latest_from_butler(WHO[sys.argv[2]], int(sys.argv[3]) if len(sys.argv) > 3 else 5):
        print("=" * 70, "\n", e["date"], "|", e["subject"], "| to:", e["to"], "| cc:", e["cc"], "| thread:",
              e["thread_id"])
        print(e["body"][:1200])
elif step == "sent":  # Butler's sent mail, newest first
    value = run("Gmail.SearchEmailsByQuery", query="in:sent newer_than:1h", max_results=int(sys.argv[2]),
                result_detail="full")
    for e in value["emails"]:
        print("=" * 70, "\n", e["date"], "|", e["subject"], "| to:", e["to"], "| cc:", e["cc"])
        print(e["body"][:700])
elif step == "event":
    value = run("GoogleCalendar.GetEvent", event_id=sys.argv[2] if len(sys.argv) > 2 else event_id())
    print(json.dumps({k: value.get(k) for k in ("status", "start", "end", "location", "description", "attendees")},
                     indent=1) if value else value)
elif step == "cal":
    value = run("GoogleCalendar.ListEvents", as_=WHO[sys.argv[2]], min_end_datetime="2026-10-24T00:00:00",
                max_start_datetime="2026-10-26T00:00:00")
    for e in (value or {}).get("events", []):
        print(e.get("id"), e.get("status"), e.get("summary"), e.get("start"))
    print("events:", len((value or {}).get("events", [])))
