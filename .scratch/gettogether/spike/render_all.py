"""Print every system email + the calendar description from render.py with sample data (ticket 08).

uv run --project ../../../../gettogether python render_all.py > ../wording-<tag>.txt
"""

from datetime import datetime

from butler import render

START = "2026-10-24T19:00:00-07:00"
dinner = {"host_name": "Chris Lee", "host_email": "campingchra@gmail.com", "start_at": START,
          "place": "482 Linden Ave", "group_threshold": 2}
notes = [{"id": 1, "text": "Street parking only", "shareable": 1},
         {"id": 2, "text": "It's a surprise birthday for Xhaka", "shareable": 0}]
guests = [{"email": "augustclee7@gmail.com"}, {"email": "xhakaout32@gmail.com"}]
august = {"name": "August Lee", "email": "augustclee7@gmail.com", "plus_ones": 1,
          "dietary_needs": "Partner is vegetarian", "guest_note": "Running 15 min late"}
xhaka = {"name": "Xhaka Out", "email": "xhakaout32@gmail.com", "plus_ones": 0, "dietary_needs": "", "guest_note": ""}


def show(title: str, body: str, subject: str | None = None, who: str = "") -> None:
    print(f"\n{'=' * 70}\n{title}{f'  →  {who}' if who else ''}")
    if subject:
        print(f"Subject: {subject}")
    print("-" * 70)
    print(body)


show("1. Draft preview (attached below Claude's reply)", render.draft_preview(dinner, notes, guests),
     who="Host, Host thread")
subject, body = render.invite(dinner, notes)
show("2. Invite", body, subject, "each Guest, own thread")
show("3. Host notice: yes", render.host_notice(august, "invited", "attending", 3), who="Host, Host thread")
show("3b. Host notice: no", render.host_notice(xhaka, "invited", "declined", 2), who="Host, Host thread")
show("3c. Host notice: changed details", render.host_notice(xhaka, "attending", "attending", 3),
     who="Host, Host thread")
subject, body = render.group_opener(dinner, [render.guest_label(august), render.guest_label(xhaka)], 3)
show("4. Group thread opener", body, subject, "To Host, cc Attending")
show("5. Welcome (late yes)", render.welcome(dinner, ["Guest C"], [render.guest_label(august), render.guest_label(xhaka), "Guest C"], 4),
     who="Group thread")
moved = dict(dinner, start_at="2026-10-24T20:00:00-07:00")
lines = render.change_lines(moved, START, None, ["Please bring a bottle of wine"])
show("6a. Change notice: group", render.change_notice(moved, lines, "group"), who="Group thread")
show("6b. Change notice: Attending outside group", render.change_notice(moved, lines, "attending"),
     who="Guest, own thread")
show("6c. Change notice: Invited (no answer yet)", render.change_notice(moved, lines, "invited"),
     who="Guest, own thread")
show("6d. Change attached below Claude's group reply", render.change_attachment(lines),
     who="Group thread (Host asked there)")
show("7a. Cancel: group", render.cancel_notice(moved, group=True), who="Group thread")
show("7b. Cancel: private", render.cancel_notice(moved, group=False), who="Invited/Attending outside group")
show("8. Calendar description", render.description(dinner, notes, [render.guest_label(august), render.guest_label(xhaka)], 3,
                                                    "arrialee7@gmail.com"), who="calendar event")
print(f"\n{'=' * 70}\nSignatures: to Host '{render.sign('x').splitlines()[-1]}', "
      f"to others '{render.sign('x', dinner).splitlines()[-1]}'")
