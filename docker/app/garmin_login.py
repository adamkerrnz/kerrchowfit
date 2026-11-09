"""One-off Garmin sign-in that saves tokens to the data volume, for accounts with 2-step verification.

Run inside the container:  python -m app.garmin_login
"""
import getpass
import os
from pathlib import Path

from garminconnect import Garmin

TOKENS = os.getenv("GARMIN_TOKENS", "/data/garmin-tokens")


def main() -> None:
    email = os.getenv("GARMIN_EMAIL") or input("Garmin email: ").strip()
    password = os.getenv("GARMIN_PASSWORD") or getpass.getpass("Garmin password: ")
    g = Garmin(email, password, return_on_mfa=True)
    res = g.login()
    if isinstance(res, tuple) and res and res[0] == "needs_mfa":
        code = input("Code from Garmin (email or authenticator app): ").strip()
        g.resume_login(res[1], code)
    Path(TOKENS).mkdir(parents=True, exist_ok=True)
    g.garth.dump(TOKENS)
    print(f"Signed in as {g.get_full_name()}. Tokens saved to {TOKENS}.")
    print("Restart the container so the app picks them up. You can now remove GARMIN_PASSWORD from the stack.")


if __name__ == "__main__":
    main()
