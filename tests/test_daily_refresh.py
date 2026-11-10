"""The claude.ai daily task (tools/daily_refresh.py) and the self-hosted server must agree."""
import importlib.util
import json
from pathlib import Path

from app import lesmills, weather

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("daily_refresh", ROOT / "tools" / "daily_refresh.py")
daily = importlib.util.module_from_spec(spec)
spec.loader.exec_module(daily)


def test_weather_labels_match_the_server():
    for prob, mm, hrs, wind, gust in [(100, 32, 12, 26, 70), (92, 8.6, 3.5, 15, 39), (55, 0.5, 0.5, 22, 37), (3, 0, 0, 11, 32), (60, 0.8, 1, 17, 32), (30, 0, 0, 30, 10)]:
        ours = daily.weather_day({"prob": prob, "mm": mm, "hrs": hrs, "wind": wind, "gust": gust})
        theirs = weather._summary(prob, mm, hrs, wind, gust, 0, 0)
        assert (ours["rain"], ours["windy"]) == (theirs["rain"], theirs["windy"])


def test_class_picking_matches_the_server():
    cards = [
        {"startDate": "10 Nov 2026", "startTime": "07:10", "className": "SPRINT", "durationMins": 30, "mainInstructorName": "Glen Ostergaard ", "siteName": "Cycle Studio"},
        {"startDate": "10 Nov 2026", "startTime": "06:10", "className": "RPM", "durationMins": 45, "mainInstructorName": "Tommi Wong", "siteName": "Cycle Studio"},
        {"startDate": "12 Nov 2026", "startTime": "07:10", "className": "THE TRIP", "durationMins": 45, "mainInstructorName": "A", "secondaryInstructorName": "B", "siteName": "Cycle Studio"},
        {"startDate": "12 Nov 2026", "startTime": "07:10", "className": "VIRTUAL SPRINT", "durationMins": 30, "mainInstructorName": "Virtual Instructor", "siteName": "Cycle Studio"},
    ]
    assert daily.pick_classes(cards) == lesmills.pick_classes(cards, "07:10")
    assert daily.CYCLE == lesmills.CYCLE


def test_weather_document_keeps_the_week_so_far(tmp_path):
    old = {"days": {"2026-11-09": {"rain": "heavy", "alerts": ["9139"]}, "2026-10-20": {"rain": "dry", "alerts": []}},
           "alerts": {"9139": {"name": "Thunderstorm Watch", "when": "Mon"}, "1": {"name": "Old", "when": ""}}}
    rows = {"days": [{"date": "2026-11-10", "prob": 100, "mm": 32, "hrs": 12, "windDir": "NNE", "wind": 26, "gust": 70, "phrase": "Breezy with rain", "alerts": ["9146"]}],
            "alerts": {"9146": {"name": "Thunderstorm Watch", "when": "Tue"}}}
    doc = daily.build_weather(rows, old, "2026-11-10", "2026-11-09T16:40:00Z")
    assert sorted(doc["days"]) == ["2026-11-09", "2026-11-10"]          # Monday kept, three-week-old day dropped
    assert doc["days"]["2026-11-10"]["rain"] == "heavy" and doc["days"]["2026-11-10"]["windy"] == "windy"
    assert sorted(doc["alerts"]) == ["9139", "9146"]                    # Monday's warning text kept, unused one dropped


def test_command_line(tmp_path):
    feed = {"responseData": {"clubs": [{"crmClubCode": "01", "clubName": "Auckland City"}], "cards": [
        {"startDate": "17 Nov 2026", "startTime": "07:10", "className": "SPRINT", "durationMins": 30, "mainInstructorName": "Glen Ostergaard", "siteName": "Cycle Studio"}]}}
    (tmp_path / "cards.json").write_text(json.dumps(feed))
    out = tmp_path / "out.json"
    assert daily.main(["x", "classes", str(tmp_path / "cards.json"), str(tmp_path / "missing.json"), str(out)]) == 0
    doc = json.loads(out.read_text())
    assert doc["club"] == "Auckland City" and doc["days"]["2026-11-17"]["instructor"] == "Glen Ostergaard"
    (tmp_path / "empty.json").write_text(json.dumps({"responseData": {"cards": []}}))
    assert daily.main(["x", "classes", str(tmp_path / "empty.json"), str(out), str(tmp_path / "out2.json")]) == 2
