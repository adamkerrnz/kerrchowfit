from app import weather


def test_thresholds():
    s = weather._summary(prob=80, mm=12, hrs=5, wind=32, gust=55, deg=20, code=63)
    assert (s["rain"], s["windy"], s["windDir"], s["phrase"]) == ("heavy", "windy", "NNE", "Rain")
    assert weather._summary(60, 2, 1, 10, 20, 0, 61)["rain"] == "rain"
    assert weather._summary(60, 0.2, 0, 10, 20, 0, 3)["rain"] == "maybe"   # likely, but next to nothing falls
    assert weather._summary(35, 0, 0, 22, 30, 0, 2)["windy"] == "breezy"
    assert weather._summary(10, 0, 0, 5, 10, 0, 0)["rain"] == "dry"
    assert weather._summary(None, None, None, None, None, None, None)["windy"] == "calm"


def _hourly(day, values):
    """24 hours for one day; `values` maps hour -> (prob, mm, wind, gust, deg, code)."""
    out = {k: [] for k in ("time", "precipitation_probability", "precipitation", "wind_speed_10m", "wind_gusts_10m", "wind_direction_10m", "weather_code")}
    for h in range(24):
        prob, mm, wind, gust, deg, code = values.get(h, (0, 0, 5, 8, 0, 0))
        out["time"].append(f"{day}T{h:02d}:00")
        for k, v in zip(list(out)[1:], (prob, mm, wind, gust, deg, code)):
            out[k].append(v)
    return out


def test_only_daytime_hours_count():
    # A storm at 2 am and at 9 pm must not make the training day look wet or windy.
    h = _hourly("2026-11-10", {2: (100, 20, 60, 90, 180, 95), 21: (100, 15, 50, 80, 180, 82)})
    day = weather.daytime_days(h)["2026-11-10"]
    assert (day["rain"], day["windy"], day["mm"]) == ("dry", "calm", 0)


def test_daytime_summary():
    h = _hourly("2026-11-10", {7: (70, 3.0, 20, 35, 90, 61), 12: (90, 8.0, 34, 52, 270, 65), 18: (40, 0.04, 10, 20, 0, 3)})
    day = weather.daytime_days(h)["2026-11-10"]
    assert day["prob"] == 90 and day["mm"] == 11.0 and day["hrs"] == 2
    assert day["wind"] == 34 and day["gust"] == 52 and day["windDir"] == "W"   # direction at the windiest hour
    assert (day["rain"], day["windy"], day["phrase"]) == ("heavy", "windy", "Heavy rain")


def test_past_days_of_the_week_are_kept():
    old = {"2026-11-01": {"x": 0}, "2026-11-09": {"x": 1}, "2026-11-10": {"x": 2}}
    new = {"2026-11-10": {"x": 9}, "2026-11-11": {"x": 3}}
    merged = weather.merge_past(new, old, "2026-11-10")
    assert sorted(merged) == ["2026-11-09", "2026-11-10", "2026-11-11"]   # yesterday kept, 9 days ago dropped
    assert merged["2026-11-10"] == {"x": 9}                                # a fresh forecast always wins
