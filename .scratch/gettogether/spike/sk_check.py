"""Ticket 09 live check: Host and Guest A email Butler; Butler's log should show each route."""
import sys
from lc import run, BUTLER, HOST, A

step = sys.argv[1]
if step == "1":
    run("Gmail.SendEmail", as_=HOST, recipient=BUTLER, subject="sk1 dinner Sat?", body="sk1 host fresh email")
    run("Gmail.SendEmail", as_=A, recipient=BUTLER, subject="sk1 question", body="sk1 guest A fresh email, no Dinner yet")
elif step == "2":
    mid = sys.argv[2]  # Host's sk1 message id (Butler's copy is the same id across mailboxes? no: use Host's sent copy)
    run("Gmail.ReplyToEmail", as_=HOST, reply_to_message_id=mid, reply_to_whom="every_recipient", body="sk2 host reply in thread")
    run("Gmail.SendEmail", as_=A, recipient=BUTLER, subject="sk2 parking?", body="sk2 guest A fresh email, Dinner exists")
    run("Gmail.SendEmail", as_=A, recipient=BUTLER, subject="Accepted: sk2 Dinner @ Sat", body="sk2 fake calendar reply")
