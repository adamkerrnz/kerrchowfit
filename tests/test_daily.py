"""The daily refresh script (app/daily.py) that replaced the scheduled Claude tasks."""
from app import daily, lesmills, weather


def _stub(monkeypatch, **results):
    calls = []
    def job(name, value):
        def run():
            calls.append(name)
            if isinstance(value, Exception):
                raise value
            return value
        return run
    monkeypatch.setattr(daily, "TASKS", {n: job(n, v) for n, v in results.items()})
    return calls


def test_runs_every_task_even_when_one_fails(monkeypatch):
    calls = _stub(monkeypatch, weather=True, classes=RuntimeError("feed down"), garmin=None, strava=False)
    assert daily.run() == {"weather": "ok", "classes": "failed", "garmin": "skipped", "strava": "failed", "prune": "ok"}
    assert calls == ["weather", "classes", "garmin", "strava"]


def test_command_line(monkeypatch, capsys):
    _stub(monkeypatch, weather=True, garmin=None)
    assert daily.main(["daily", "weather", "garmin"]) == 0
    assert capsys.readouterr().out.splitlines() == ["weather: ok", "garmin: skipped"]
    _stub(monkeypatch, weather=False)
    assert daily.main(["daily", "weather"]) == 1
    assert daily.main(["daily", "nope"]) == 2


def test_refreshes_report_failure(monkeypatch):
    def boom(*a, **k):
        raise OSError("offline")
    monkeypatch.setattr(weather.httpx, "get", boom)
    monkeypatch.setattr(lesmills.httpx, "get", boom)
    assert weather.refresh() is False
    assert lesmills.refresh() is False
