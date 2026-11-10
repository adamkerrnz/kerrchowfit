import base64
import json

import pytest

from app import garmin, store
from app.errors import ToolError


@pytest.fixture(autouse=True)
def clean():
    garmin.clear_key()
    yield
    garmin.clear_key()


def _jwt(exp):
    body = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return f"h.{body}.s"


def test_token_expiry_is_read_from_the_jwt():
    assert garmin._jwt_exp(_jwt(1_900_000_000)) == 1_900_000_000
    assert garmin._jwt_exp("not-a-jwt") > 0                      # unreadable: falls back to an hour from now


def test_key_from_the_page_wins_over_the_environment(monkeypatch):
    monkeypatch.setenv("GARMIN_PERSONAL_API_KEY", "env-key")
    assert (garmin.api_key(), garmin.key_source()) == ("env-key", "env")
    monkeypatch.setattr(garmin, "_exchange", lambda key: {"token": "t", "expires_at": 9e9})
    garmin.save_key("  page-key ")
    assert (garmin.api_key(), garmin.key_source()) == ("page-key", "saved")


def test_a_refused_key_is_not_saved(monkeypatch):
    def refuse(key):
        raise ToolError("needs_reauth", "no")
    monkeypatch.setattr(garmin, "_exchange", refuse)
    with pytest.raises(ToolError):
        garmin.save_key("bad")
    assert not garmin.configured()


def test_token_is_reused_until_near_expiry(monkeypatch):
    calls = []
    monkeypatch.setattr(garmin, "_exchange", lambda key: calls.append(key) or {"token": f"t{len(calls)}", "expires_at": 9e9})
    garmin.save_key("k")
    assert garmin._token() == "t1" and len(calls) == 1
    store.kv_put(garmin.TOKEN_KV, {"token": "old", "expires_at": 0})
    assert garmin._token() == "t2"


def test_sleep_nights_are_mapped_with_overnight_hrv(monkeypatch):
    def fake_get(path, params=None):
        if path.startswith("/sleep-service"):
            return [{"calendarDate": "2026-11-09", "sleepTimeSeconds": 27000, "deepSleepSeconds": 5000, "lightSleepSeconds": 15000,
                     "remSleepSeconds": 6000, "awakeSleepSeconds": 1000, "sleepScores": {"overall": {"value": 81}}},
                    {"calendarDate": "2026-11-10", "sleepTimeSeconds": 0}]   # no sleep recorded: skipped
        return {"hrvSummaries": [{"calendarDate": "2026-11-09", "lastNightAvg": 58}]}
    monkeypatch.setattr(garmin, "_get", fake_get)
    out = garmin.sleep_range("2026-11-04", "2026-11-10")
    assert out["nights"] == [{"date": "2026-11-09", "sleep_seconds": 27000, "sleep_score": 81, "deep_sleep_seconds": 5000,
                              "light_sleep_seconds": 15000, "rem_sleep_seconds": 6000, "awake_seconds": 1000, "avg_overnight_hrv": 58}]


def test_intensity_minutes_sum_by_week_with_vigorous_doubled(monkeypatch):
    days = [{"calendarDate": "2026-11-09", "intensityMinutes": {"goal": 200, "moderate": 30, "vigorous": 10}},  # Monday
            {"calendarDate": "2026-11-10", "intensityMinutes": {"goal": 200, "moderate": 5, "vigorous": 0}},
            {"calendarDate": "2026-11-08", "intensityMinutes": {"moderate": 20, "vigorous": 5}}]                # the Sunday before
    monkeypatch.setattr(garmin, "_get", lambda path, params=None: {"data": days})
    weeks = garmin.intensity_minutes("2026-11-10", 1)["weekly_data"]
    assert weeks == [
        {"week_start": "2026-11-09", "weekly_goal": 200, "moderate_minutes": 35, "vigorous_minutes": 10, "total_minutes": 55},
        {"week_start": "2026-11-02", "weekly_goal": 150, "moderate_minutes": 20, "vigorous_minutes": 5, "total_minutes": 30},
    ]
