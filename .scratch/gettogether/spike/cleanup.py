"""Silently delete this run's events."""
from lc import run, load
s = load()
for k in ["LC1", "LC2", "LC3", "LC4", "LC5"]:
    print(k, run("GoogleCalendar.DeleteEvent", event_id=s[k], send_updates="nobody")[:60])
