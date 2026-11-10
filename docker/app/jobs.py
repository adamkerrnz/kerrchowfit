"""Background schedule: the daily refresh (app/daily.py) each morning, plus weather every 3 hours and Strava warm-ups hourly."""
import datetime as dt
import logging
import os
import threading

from apscheduler.schedulers.background import BackgroundScheduler

from . import daily, garmin, lesmills, store, strava, weather

log = logging.getLogger("jobs")
TZ = os.getenv("TZ", "Pacific/Auckland")
# Empty turns the built-in daily run off (e.g. when the host's cron runs `python -m app.daily` instead).
# GARMIN_REFRESH_TIME is the older name for the same setting.
DAILY_TIME = os.getenv("DAILY_REFRESH_TIME", os.getenv("GARMIN_REFRESH_TIME", "05:40")).strip()
_sched: BackgroundScheduler | None = None


def _safe(fn, name):
    def run():
        try:
            fn()
        except Exception:
            log.exception("%s failed", name)
    return run


def start() -> None:
    global _sched
    _sched = BackgroundScheduler(timezone=TZ)
    if DAILY_TIME:
        hh, mm = (DAILY_TIME.split(":") + ["0"])[:2]
        # Weather, classes, Garmin, Strava and cache clean-up; tasks that aren't set up yet skip themselves.
        _sched.add_job(_safe(daily.run, "daily refresh"), "cron", hour=int(hh), minute=int(mm), id="daily")
    _sched.add_job(_safe(weather.refresh, "weather"), "cron", hour="*/3", minute=5, id="weather")
    _sched.add_job(_safe(strava.warm_best_efforts, "strava best efforts"), "cron", minute=20, id="strava")
    _sched.start()

    def first_run():  # fill anything missing straight after a (re)deploy
        if not store.doc_get(weather.DOC):
            _safe(weather.refresh, "weather")()
        if lesmills.enabled() and not store.doc_get(lesmills.DOC):
            _safe(lesmills.refresh, "les mills timetable")()
        latest = store.doc_get("garmin/latest") or {}
        if garmin.configured() and latest.get("date") != dt.datetime.now(garmin.TZ).date().isoformat():
            _safe(garmin.snapshot, "garmin snapshot")()
    threading.Thread(target=first_run, daemon=True).start()


def prune() -> None:
    """Drop cache rows nothing will read again, so the database doesn't grow for ever."""
    day = 86400
    n = store.kv_prune("strava:acts:", 2 * day)      # weekly activity lists; a new key starts each Monday
    n += store.kv_prune("strava:state:", day)        # unfinished Strava sign-ins
    for kind in ("summary", "hrv", "sleep", "im"):
        n += store.kv_prune(f"garmin:{kind}:", 14 * day)  # per-day Garmin answers
    if n:
        log.info("cache clean-up removed %d rows", n)


def stop() -> None:
    if _sched:
        _sched.shutdown(wait=False)
