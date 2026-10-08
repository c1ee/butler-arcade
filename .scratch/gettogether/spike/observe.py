"""Observe each mailbox: every RUN-tagged message with labels + thread."""
import sys
from lc import run, load, HOST, A, B, BUTLER

s = load()
who = {"host": HOST, "A": A, "B": B, "butler": BUTLER}
for name in sys.argv[1:] or ["host", "A", "B"]:
    v = run("Gmail.SearchEmailsByQuery", as_=who[name], query=s["run"], result_detail="lightweight",
            max_results=50, include_spam_trash=True)
    print(f"== {name} ({v['num_emails']})")
    for e in sorted(v["emails"], key=lambda e: e["date"]):
        labels = ",".join(l for l in e["label_ids"] if l not in ("UNREAD", "IMPORTANT"))
        print(f"  thr={e['thread_id'][-6:]} [{labels}] {e['subject'][:95]}")
