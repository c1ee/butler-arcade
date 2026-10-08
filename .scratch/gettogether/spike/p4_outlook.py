"""P4: non-Gmail guest C (Outlook, manual observation). Group cc-add, private thread, calendar invite."""
import json, time
from lc import run, load, save, HOST, A, C, STATE

RUN = "ck9"
s = {"run": RUN, "t0": int(time.time())}
s["M4"] = run("Gmail.SendEmail", recipient=HOST, cc=[A], subject=f"LC-M4 {RUN} group", body="Group test: host + A. Butler adds C next.")
time.sleep(5)
s["M4a"] = run("Gmail.ReplyToEmail", reply_to_message_id=s["M4"]["id"], reply_to_whom="every_recipient", cc=[C],
               body="Butler reply-all on its own message, adding C via cc. (1/3 for C)")
time.sleep(20)
last = run("Gmail.SearchEmailsByQuery", as_=HOST, query=f"{RUN} LC-M4", result_detail="lightweight", max_results=10)
last = sorted(last["emails"], key=lambda e: e["date"])[-1]
s["M4h"] = run("Gmail.ReplyToEmail", as_=HOST, reply_to_message_id=last["message_id"], reply_to_whom="every_recipient",
               body="Host reply-all. (2/3 for C)")
time.sleep(20)
inbox = run("Gmail.SearchEmailsByQuery", query=f"in:inbox {RUN} LC-M4", result_detail="lightweight", max_results=10)
hm = [e for e in inbox["emails"] if HOST in e["sender"]][-1]
s["M4b"] = run("Gmail.ReplyToEmail", reply_to_message_id=hm["message_id"], reply_to_whom="only_the_sender", cc=[A, C],
               body="Butler reply to host only + cc A, C. (3/3 for C)")
s["M5"] = run("Gmail.SendEmail", recipient=C, subject=f"LC-M5 {RUN} private to C", body="Hi C, private test from Butler. Please reply.")
s["LC6"] = run("GoogleCalendar.CreateEvent", summary=f"LC6 {RUN} outlook invite", start_datetime="2026-10-24T19:00:00",
               end_datetime="2026-10-24T22:00:00", location="Host's place", attendee_emails=[C],
               send_notifications_to_attendees="all")["event"]["id"]
(STATE.parent / "state_ck9.json").write_text(json.dumps(s, indent=2, default=str))
print("M4 thr", s["M4"]["thread_id"], "| M4a", s["M4a"]["thread_id"], "| M4b", s["M4b"]["thread_id"], "| M5", s["M5"]["thread_id"], "| LC6", s["LC6"])
