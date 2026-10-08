"""P3: Butler polls inbox, checks thread mapping + RSVP state, replies in group via only_the_sender+cc."""
from lc import run, load, save, HOST, A, B

s = load()
t0 = s["t0"]
for q in [f"after:{t0}", f"in:inbox after:{t0}", f"in:inbox -from:me after:{t0}"]:
    v = run("Gmail.SearchEmailsByQuery", query=q, result_detail="lightweight", max_results=50)
    print(f"== {q!r}: {v['num_emails']}")
    if "in:inbox -from:me" in q:
        s["inbox"] = v["emails"]
        for e in sorted(v["emails"], key=lambda e: e["date"]):
            print(f"  thr={e['thread_id']} from={e['sender'][:40]!r} date={e['date']!r}\n    subj={e['subject'][:100]!r}")
print("M1 thread:", s["M1"]["thread_id"], "| M3 thread:", s["M3"]["thread_id"])
for k in ["LC1", "LC4"]:
    ev = run("GoogleCalendar.GetEvent", event_id=s[k])
    ev = ev.get("event", ev)
    print(k, "attendees:", [(a["email"].split("@")[0], a.get("responseStatus"), a.get("optional")) for a in ev.get("attendees", [])])
host_msg = [e for e in s["inbox"] if "LC-M3" in e["subject"] and "campingchra" in e["sender"]]
if host_msg:
    s["M3_butler2"] = run("Gmail.ReplyToEmail", reply_to_message_id=host_msg[-1]["message_id"], reply_to_whom="only_the_sender",
                          cc=[A, B], body="Butler reply to host's message: only_the_sender + cc A,B.")
    g = run("Gmail.GetEmail", email_id=s["M3_butler2"]["id"])
    print("M3_butler2 thr:", s["M3_butler2"]["thread_id"], "headers:", g["email_addresses"], "subj:", g["subject"])
save(s)
