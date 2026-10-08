"""P2: simulate human actions from host/A/B mailboxes and calendars."""
from lc import run, load, save, HOST, A, B

s = load()
R = s["run"]


def find(user, q):
    v = run("Gmail.SearchEmailsByQuery", as_=user, query=f"{R} {q}", result_detail="lightweight", max_results=10, include_spam_trash=True)
    return sorted(v["emails"], key=lambda e: e["date"])


s["h_rsvp_LC1"] = run("GoogleCalendar.RespondToEvent", as_=HOST, event_id=s["LC1"], response="accepted", send_updates="all")
s["a_rsvp_LC4"] = run("GoogleCalendar.RespondToEvent", as_=A, event_id=s["LC4"], response="accepted", send_updates="all")
s["b_rsvp_LC4"] = run("GoogleCalendar.RespondToEvent", as_=B, event_id=s["LC4"], response="declined", send_updates="all")
print("rsvp:", s["h_rsvp_LC1"], "|", s["a_rsvp_LC4"], "|", s["b_rsvp_LC4"])

m1 = find(A, "LC-M1")[-1]
s["a_reply_M1"] = run("Gmail.ReplyToEmail", as_=A, reply_to_message_id=m1["message_id"], reply_to_whom="only_the_sender", body="yes I'm in")
inv = find(A, "Invitation LC4")[-1]
s["a_reply_inv"] = run("Gmail.ReplyToEmail", as_=A, reply_to_message_id=inv["message_id"], reply_to_whom="only_the_sender", body="what's parking like?")
last = find(HOST, "LC-M3")[-1]
s["h_replyall_M3"] = run("Gmail.ReplyToEmail", as_=HOST, reply_to_message_id=last["message_id"], reply_to_whom="every_recipient", body="host reply-all")
save(s)
for k in ["a_reply_M1", "a_reply_inv", "h_replyall_M3"]:
    print(k, s[k] and s[k].get("id"))
