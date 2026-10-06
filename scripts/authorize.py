"""One-time Google consent for Butler's account, through Arcade.

Run: `uv run scripts/authorize.py`. Prints "already authorized" if the grant exists.
"""

from arcadepy import Arcade

from butler import config


def main() -> None:
    settings = config.load()
    client = Arcade(api_key=settings.arcade_api_key)
    auth = client.auth.start(user_id=settings.butler_user_id, provider="google", scopes=config.GOOGLE_SCOPES)
    if auth.status == "completed":
        print(f"{settings.butler_user_id} is already authorized for Gmail and Calendar.")
        return

    # Arcade only completes the grant in a browser signed in to Arcade as the same account as the user id,
    # so print the link instead of opening the default browser.
    print(f"Open this link in a browser signed in to Arcade as {settings.butler_user_id}, then sign in")
    print(f"to Google as {settings.butler_user_id} and allow access:\n\n  {auth.url}\n")
    print("Waiting for consent…")
    auth = client.auth.wait_for_completion(auth)
    if auth.status != "completed":
        raise SystemExit(f"Authorization ended with status {auth.status!r}. Run this script again.")
    print(f"{settings.butler_user_id} is authorized for Gmail and Calendar.")


if __name__ == "__main__":
    main()
