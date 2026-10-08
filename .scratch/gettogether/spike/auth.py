"""Grant per account (union of scopes). Usage: auth.py [email ...]; default Butler. Outlook addresses use Microsoft."""
import sys
from lc import client, BUTLER, SCOPES, MS_SCOPES

for user in sys.argv[1:] or [BUTLER]:
    ms = user.endswith(("@outlook.com", "@hotmail.com", "@live.com"))
    r = client.auth.start(user_id=user, provider="microsoft" if ms else "google", scopes=MS_SCOPES if ms else SCOPES)
    print(f"{user}: {r.status}")
    if r.status != "completed":
        print("  URL:", r.url)
