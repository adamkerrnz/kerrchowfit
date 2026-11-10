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


# ---- forecast.py: the stand-alone builder the claude.ai daily task runs ----
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

from app import forecast

NZ = ZoneInfo("Pacific/Auckland")
NOW = dt.datetime(2026, 11, 10, 6, 0, tzinfo=NZ)
AUCKLAND_BOX = "-36.5,174.5 -36.5,175.0 -37.2,175.0 -37.2,174.5 -36.5,174.5"
WELLINGTON_BOX = "-41.0,174.5 -41.0,175.0 -41.5,175.0 -41.5,174.5 -41.0,174.5"


def _cap(ident="2.49.0.0.554.0.NZ.20261109.1", polygon=AUCKLAND_BOX, onset="2026-11-10T09:00:00+13:00",
         expires="2026-11-11T01:00:00+13:00", msg="Alert", headline="Heavy Rain Watch"):
    return f"""<?xml version="1.0"?><alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
      <identifier>{ident}</identifier><status>Actual</status><msgType>{msg}</msgType>
      <info><language>en-NZ</language><event>rain</event><headline>{headline}</headline>
      <onset>{onset}</onset><expires>{expires}</expires>
      <area><areaDesc>Auckland</areaDesc><polygon>{polygon}</polygon></area></info></alert>"""


def test_alert_for_our_point_only():
    a = forecast.parse_alert(_cap(), NZ, NOW)
    assert a["name"] == "Heavy Rain Watch" and a["when"] == "Tue, Nov 10 9:00 AM to Wed, Nov 11 1:00 AM"
    assert forecast.parse_alert(_cap(polygon=WELLINGTON_BOX), NZ, NOW) is None   # the polygon decides, not the area name
    assert forecast.parse_alert(_cap(msg="Cancel"), NZ, NOW) is None
    assert forecast.parse_alert(_cap(expires="2026-11-10T05:00:00+13:00", onset="2026-11-09T05:00:00+13:00"), NZ, NOW) is None  # over
    assert forecast.parse_alert("<html>blocked</html>", NZ, NOW) is None
    assert forecast.parse_alert("not xml", NZ, NOW) is None


def test_feed_links_stay_on_metservice():
    rss = """<rss><channel><link>https://alerts.metservice.com/cap/rss</link>
      <item><link>https://alerts.metservice.com/cap/alert?id=1</link></item>
      <item><link>https://evil.example/cap/alert?id=2</link></item>
      <item><link>http://alerts.metservice.com/cap/alert?id=3</link></item></channel></rss>"""
    assert forecast.feed_links(rss) == ["https://alerts.metservice.com/cap/alert?id=1"]


def test_build_tags_daytime_overlap_and_keeps_past_warnings():
    hourly = {k: a + b for (k, a), b in zip(_hourly("2026-11-10", {}).items(), _hourly("2026-11-11", {}).values())}
    old = {"days": {"2026-11-09": {"alerts": ["old1"]}, "2026-11-10": {"alerts": ["gone"]}},
           "alerts": {"old1": {"name": "Thunderstorm Watch", "when": "x"}, "gone": {"name": "Stale", "when": "y"}}}
    doc = forecast.build(hourly, [_cap(), _cap()], old, NOW)
    (aid,) = doc["days"]["2026-11-10"]["alerts"]                 # duplicates collapse
    assert doc["days"]["2026-11-11"]["alerts"] == []             # it ends 1 am Wednesday: not in Wednesday's daytime
    assert set(doc["alerts"]) == {aid, "old1"} and doc["source"] == "open-meteo"
    assert doc["days"]["2026-11-09"] == {"alerts": ["old1"]}


def test_command_line(tmp_path):
    script = Path(forecast.__file__)
    (tmp_path / "caps").mkdir()
    (tmp_path / "caps" / "1.xml").write_text(_cap(expires="2099-01-01T00:00:00+13:00"), encoding="utf-8")
    (tmp_path / "om.json").write_text(json.dumps({"hourly": _hourly("2026-11-10", {})}), encoding="utf-8")
    run = lambda *a: subprocess.run([sys.executable, "-I", str(script), *a], cwd=tmp_path, capture_output=True, text=True)
    r = run("build", "om.json", "caps", "missing.json", "out.json")
    assert r.returncode == 0, r.stderr
    out = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert out["days"]["2026-11-10"]["alerts"] and "Heavy Rain Watch" in r.stdout
    (tmp_path / "bad.json").write_text("<html>", encoding="utf-8")
    assert run("build", "bad.json", "caps", "missing.json", "out2.json").returncode == 2
    assert run("links", "nope.xml").returncode == 0
