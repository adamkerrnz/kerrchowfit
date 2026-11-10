import datetime as dt

from app import garmin, store


def test_primary_training_device_is_preferred():
    data = {"111": {"trainingStatus": 1}, "222": {"trainingStatus": 7, "primaryTrainingDevice": True}}
    assert garmin._pick_device(data) == ("222", data["222"])
    assert garmin._pick_device({"111": {"a": 1}}) == ("111", {"a": 1})   # one device, nothing flagged
    assert garmin._pick_device({}) == (None, {})
    assert garmin._pick_device(None) == (None, {})


def test_vo2_history_fills_a_few_days_per_call(monkeypatch):
    calls = []
    monkeypatch.setattr(garmin, "_vo2_day", lambda day: calls.append(day) or {"generic": 50.0, "cycling": None})
    today = dt.datetime.now(garmin.TZ).date()
    start, end = (today - dt.timedelta(days=20)).isoformat(), today.isoformat()

    trend, _ = garmin.vo2_trend(start, end, False, budget=5)
    assert len(calls) == 5 and calls[0] == end            # newest first, and no more than the budget
    assert [p["date"] for p in trend["trend"]] == sorted(calls)

    garmin.vo2_trend(start, end, False, budget=5)
    assert len(calls) == 10                                 # 5 more past days; today came from the cache

    for _ in range(5):
        garmin.vo2_trend(start, end, False, budget=5)
    assert len(set(calls)) == 21                            # the whole range is filled in the end


def test_a_past_day_cached_before_it_ended_is_fetched_once_more(monkeypatch):
    calls = []
    monkeypatch.setattr(garmin, "_vo2_day", lambda day: calls.append(day) or {"generic": 51.0, "cycling": None})
    day = (dt.datetime.now(garmin.TZ).date() - dt.timedelta(days=400)).isoformat()
    store.kv_put(f"garmin:vo2:{day}", {"generic": 49.0, "cycling": None})
    # Pretend it was stored at midday on that day, before any evening activity.
    midday = dt.datetime.combine(dt.date.fromisoformat(day), dt.time(12), garmin.TZ).timestamp()
    with store._lock:
        store._db().execute("UPDATE kv SET stored = ? WHERE key = ?", (midday, f"garmin:vo2:{day}"))
        store._db().commit()

    trend, _ = garmin.vo2_trend(day, day, False)
    assert calls == [day] and trend["latest_vo2_max"] == 51.0
    garmin.vo2_trend(day, day, False)
    assert calls == [day]                                   # now final: not fetched again
