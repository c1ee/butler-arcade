"""P1: Butler creates/updates events and sends mail. Tag RUN in every subject/title."""
import time
from lc import run, save, HOST, A, B

RUN = "rk7"
s = {"run": RUN, "t0": int(time.time())}
D, S, E = "2026-10-24", "T19:00:00", "T22:00:00"


def ev(key, title, attendees, send):
    v = run("GoogleCalendar.CreateEvent", summary=f"{title} {RUN}", start_datetime=D + S, end_datetime=D + E,
            description=f"{title} description v1", location="Host's place", attendee_emails=attendees,
            send_notifications_to_attendees=send)
    s[key] = v["event"]["id"]


ev("LC1", "LC1 create host all", [HOST], "all")
ev("LC2", "LC2 create host nobody", [HOST], "nobody")
ev("LC3", "LC3 add A", [HOST], "all")
ev("LC4", "LC4 description silent", [HOST, A, B], "all")
ev("LC5", "LC5 remove B", [HOST, A, B], "all")
time.sleep(20)
run("GoogleCalendar.UpdateEvent", event_id=s["LC3"], attendee_emails_to_add=[A], send_notifications_to_attendees="all")
run("GoogleCalendar.UpdateEvent", event_id=s["LC4"], updated_description="LC4 description v2: street parking only", send_notifications_to_attendees="nobody")
run("GoogleCalendar.UpdateEvent", event_id=s["LC5"], attendee_emails_to_remove=[B], send_notifications_to_attendees="all")

s["M1"] = run("Gmail.SendEmail", recipient=A, subject=f"LC-M1 {RUN} private to A", body="Hi A, private test from Butler.")
s["M2"] = run("Gmail.SendEmail", recipient=f"{HOST}, {A}", subject=f"LC-M2 {RUN} comma recipient", body="Two recipients in one comma-separated To.")
s["M3"] = run("Gmail.SendEmail", recipient=HOST, cc=[A], subject=f"LC-M3 {RUN} group", body="Group test: host + A. Butler adds B next.")
time.sleep(5)
s["M3r"] = run("Gmail.ReplyToEmail", reply_to_message_id=s["M3"]["id"], reply_to_whom="every_recipient", cc=[B],
               body="Butler reply-all on its own message, adding B via cc.")
save(s)
print({k: (v if isinstance(v, (str, int)) else v.get("thread_id")) for k, v in s.items()})
