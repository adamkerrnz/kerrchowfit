"""Shared set-up: make the server importable as `app` and point it at a throwaway database."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "docker"))

_tmp = tempfile.mkdtemp(prefix="kerrchowfit-test-")
os.environ["DB_PATH"] = os.path.join(_tmp, "test.db")
os.environ["GARMIN_TOKENS"] = os.path.join(_tmp, "garmin-tokens")
os.environ["TZ"] = "Pacific/Auckland"
for name in ("BASIC_AUTH_USER", "BASIC_AUTH_PASSWORD", "ALLOW_NO_LOGIN", "GARMIN_EMAIL", "GARMIN_PASSWORD",
             "STRAVA_CLIENT_ID", "STRAVA_CLIENT_SECRET", "STRAVA_REFRESH_TOKEN"):
    os.environ.pop(name, None)
