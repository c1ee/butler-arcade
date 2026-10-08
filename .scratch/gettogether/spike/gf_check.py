"""Ticket 11 live check: Guests RSVP by email and on the calendar (run tag gf1).

Steps: `host <text>` Host fresh email · `reply <who> <text>` reply to Butler's latest email in that inbox ·
`calendar <who> <accepted|declined|tentative> <event id>` click the invite's button ·
`inbox <who>` latest emails from Butler · `event <id>` Butler's calendar event.
"""
import json
import sys

from lc import A, B, BUTLER, HOST, run

WHO = {"host": HOST, "a": A, "b": B}


def latest_from_butler(account, n=5):
    value = run("Gmail.SearchEmailsByQuery", as_=account, query=f"from:{BUTLER} newer_than:1h", max_results=n,
                result_detail="full")
    return value["emails"]


step = sys.argv[1]
if step == "host":
    run("Gmail.SendEmail", as_=HOST, recipient=BUTLER, subject="gf1 dinner", body=sys.argv[2])
elif step == "reply":
    mid = latest_from_butler(WHO[sys.argv[2]], 1)[0]["message_id"]
    print(run("Gmail.ReplyToEmail", as_=WHO[sys.argv[2]], reply_to_message_id=mid, reply_to_whom="only_the_sender",
              body=sys.argv[3]))
elif step == "calendar":
    print(run("GoogleCalendar.RespondToEvent", as_=WHO[sys.argv[2]], event_id=sys.argv[4], response=sys.argv[3],
              send_updates="all"))
elif step == "inbox":
    for e in latest_from_butler(WHO[sys.argv[2]], int(sys.argv[3]) if len(sys.argv) > 3 else 5):
        print("=" * 70, "\n", e["date"], "|", e["subject"], "| to:", e["to"], "| thread:", e["thread_id"])
        print(e["body"][:1500])
elif step == "event":
    value = run("GoogleCalendar.GetEvent", event_id=sys.argv[2])
    print(json.dumps({k: value[k] for k in ("start", "location", "description", "attendees")}, indent=1))
