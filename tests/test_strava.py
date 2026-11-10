import datetime as dt

from app import store, strava


def _acts(dates):
    return [{"id": i, "start_date_local": d + "T07:00:00Z", "sport_type": "Run", "distance": 5000, "moving_time": 1500}
            for i, d in enumerate(dates)]


def _streak(monkeypatch, dates):
    monkeypatch.setattr(strava, "_year_of_activities", lambda refresh: (_acts(dates), 0.0))
    return strava.get_active_streak({}, False)[0]


def _monday(weeks_ago=0):
    today = dt.datetime.now(strava.TZ).date()
    return today - dt.timedelta(days=today.weekday(), weeks=weeks_ago)


def test_streak_counts_weeks_and_activities_across_the_streak(monkeypatch):
    dates = [_monday(0).isoformat(), _monday(1).isoformat(), (_monday(1) + dt.timedelta(days=2)).isoformat(), _monday(2).isoformat(),
             _monday(4).isoformat()]  # a gap at 3 weeks ago ends the streak
    assert _streak(monkeypatch, dates) == {"length": 3, "streak_status": "Ongoing", "valid_activity_count": 4}


def test_streak_is_pending_until_this_week_has_an_activity(monkeypatch):
    s = _streak(monkeypatch, [_monday(1).isoformat(), _monday(2).isoformat()])
    assert (s["length"], s["streak_status"]) == (2, "Pending")
    assert _streak(monkeypatch, [])["length"] == 0


def test_activity_mapping():
    m = strava._map({"id": 7, "name": "Morning Run", "sport_type": "Run", "distance": 5000, "moving_time": 1500,
                     "suffer_score": 41.6, "pr_count": 2, "start_date_local": "2026-11-09T06:30:00Z"})
    assert m["start_local"] == "2026-11-09T06:30:00"          # local wall time, without Strava's misleading Z
    assert m["summary"] == {"moving_time": 1500, "distance": 5.0, "pr_count": 2, "achievement_count": 0,
                            "relative_effort": 42, "avg_pace_display": "5:00 /km"}
    assert "avg_pace_display" not in strava._map({"sport_type": "Ride", "distance": 20000, "moving_time": 3600})["summary"]


def test_sign_in_state_is_single_use():
    state = strava.new_state()
    assert state in strava.auth_url("http://x/strava/callback", state)
    assert strava.check_state(state) is True
    assert strava.check_state(state) is False      # can't be replayed
    assert strava.check_state("made-up") is False
    assert strava.check_state(None) is False


def test_sign_in_state_expires(monkeypatch):
    state = strava.new_state()
    monkeypatch.setattr(strava, "STATE_TTL", -1)
    assert strava.check_state(state) is False


def test_best_efforts_say_they_cover_twelve_months(monkeypatch):
    monkeypatch.setattr(strava, "_year_of_activities", lambda refresh: ([], 0.0))
    payload, _ = strava.get_athlete_best_efforts({}, False)
    assert payload == {"efforts": [], "all_time": False, "window_months": 12}
