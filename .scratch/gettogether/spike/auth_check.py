"""Items 13/14: grant complete? auth.start on subset returns completed? ReplyToEmail needs no new prompt?"""
from lc import client, BUTLER, SCOPES

r = client.auth.start(user_id=BUTLER, provider="google", scopes=SCOPES)
print("union:", r.status)
r = client.auth.start(user_id=BUTLER, provider="google", scopes=SCOPES[:1])
print("subset gmail.send:", r.status, "token?", bool(r.context and r.context.token))
for t in ["Gmail.ReplyToEmail", "Gmail.SendEmail", "Gmail.SearchEmailsByQuery", "Gmail.GetThread",
          "GoogleCalendar.CreateEvent", "GoogleCalendar.UpdateEvent", "GoogleCalendar.GetEvent"]:
    a = client.tools.authorize(tool_name=t, user_id=BUTLER)
    print(t, a.status)
