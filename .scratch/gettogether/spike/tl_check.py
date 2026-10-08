"""Ticket 10 live check: the Host sets up a Dinner with Butler by email (run tag tl1).

Steps: `1` Host's fresh email (no place) · `2 <text>` Host replies to Butler's latest message ·
`inbox <who>` latest emails from Butler in that account · `event <id>` Butler's calendar event.
"""
import json
import sys

from lc import A, B, BUTLER, HOST, run

WHO = {"host": HOST, "a": A, "b": B}


def latest_from_butler(account):
    value = run("Gmail.SearchEmailsByQuery", as_=account, query=f"from:{BUTLER} newer_than:1h", max_results=5,
                result_detail="full")
    return value["emails"]


step = sys.argv[1]
if step == "1":
    run("Gmail.SendEmail", as_=HOST, recipient=BUTLER, subject="tl1 dinner",
        body=f"Hi Butler! Can you set up dinner on Saturday 10/24 at 7pm? Please invite {A} and {B}.")
elif step == "2":
    mid = latest_from_butler(HOST)[0]["message_id"]
    run("Gmail.ReplyToEmail", as_=HOST, reply_to_message_id=mid, reply_to_whom="only_the_sender", body=sys.argv[2])
elif step == "inbox":
    for e in latest_from_butler(WHO[sys.argv[2]]):
        print("=" * 70, "\n", e["subject"], "| to:", e["to"], "| cc:", e["cc"], "| thread:", e["thread_id"])
        print(e["body"])
elif step == "event":
    print(json.dumps(run("GoogleCalendar.GetEvent", event_id=sys.argv[2]), indent=1)[:3000])
