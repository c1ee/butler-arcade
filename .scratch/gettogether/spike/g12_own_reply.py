"""Ticket 12: ReplyToEmail on Butler's own message. only_the_sender vs every_recipient, + cc."""
from lc import A, B, HOST, run

op = run("Gmail.SendEmail", recipient=HOST, cc=[A], subject="g12 opener test", body="g12 opener: To host, cc A.")
print("opener", op)
r1 = run("Gmail.ReplyToEmail", reply_to_message_id=op["id"], reply_to_whom="only_the_sender", cc=[A, B],
         body="g12 r1: only_the_sender on Butler's own opener, cc A+B.")
print("r1", r1)
if r1:
    g = run("Gmail.GetEmail", email_id=r1["id"])
    print("r1 to/cc:", g.get("to"), "|", g.get("cc"), "| thread", g.get("thread_id"))
r2 = run("Gmail.ReplyToEmail", reply_to_message_id=op["id"], reply_to_whom="every_recipient", cc=[HOST, A, B],
         body="g12 r2: every_recipient on Butler's own opener, cc host+A+B (dupes should drop).")
print("r2", r2)
if r2:
    g = run("Gmail.GetEmail", email_id=r2["id"])
    print("r2 to/cc:", g.get("to"), "|", g.get("cc"), "| thread", g.get("thread_id"))
