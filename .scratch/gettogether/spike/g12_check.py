"""Ticket 12 live check: the Group thread (run tag g12). Threshold 1 so A starts it and B is the late joiner.

Steps: `butler` run Butler (db /tmp/butler_g12.db, poll 15s) · `host <text>` Host fresh email ·
`reply <who> <text>` reply to Butler's latest email to that account, to Butler only ·
`all <who> <text>` reply-all to Butler's latest Group thread email · `inbox <who> [n]` · `event <id>`.
"""
import json
import sys
import time

from lc import A, B, BUTLER, HOST, run

WHO = {"host": HOST, "a": A, "b": B}


def latest_from_butler(account, n=5, query=""):
    value = run("Gmail.SearchEmailsByQuery", as_=account, query=f"from:{BUTLER} newer_than:1h {query}", max_results=n,
                result_detail="full")
    return value["emails"]


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
    settings = replace(config.load(), db_path="/tmp/butler_g12.db")
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
    run("Gmail.SendEmail", as_=HOST, recipient=BUTLER, subject="g12 dinner", body=sys.argv[2])
elif step == "reply":
    mid = latest_from_butler(WHO[sys.argv[2]], 1)[0]["message_id"]
    print(run("Gmail.ReplyToEmail", as_=WHO[sys.argv[2]], reply_to_message_id=mid, reply_to_whom="only_the_sender",
              body=sys.argv[3]))
elif step == "all":
    mid = latest_from_butler(WHO[sys.argv[2]], 1, 'subject:"Group thread"')[0]["message_id"]
    print(run("Gmail.ReplyToEmail", as_=WHO[sys.argv[2]], reply_to_message_id=mid, reply_to_whom="every_recipient",
              body=sys.argv[3]))
elif step == "inbox":
    for e in latest_from_butler(WHO[sys.argv[2]], int(sys.argv[3]) if len(sys.argv) > 3 else 5):
        print("=" * 70, "\n", e["date"], "|", e["subject"], "| to:", e["to"], "| cc:", e["cc"], "| thread:",
              e["thread_id"])
        print(e["body"][:1200])
elif step == "event":
    value = run("GoogleCalendar.GetEvent", event_id=sys.argv[2])
    print(json.dumps({k: value[k] for k in ("start", "location", "description", "attendees")}, indent=1))
