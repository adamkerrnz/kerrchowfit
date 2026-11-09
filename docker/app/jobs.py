"""Background schedule (replaces the scheduled Claude tasks): Garmin each morning, weather every 3 hours."""
import datetime as dt
import logging
import os
import threading

from apscheduler.schedulers.background import BackgroundScheduler

from . import garmin, store, strava, weather

log = logging.getLogger("jobs")
TZ = os.getenv("TZ", "Pacific/Auckland")
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
    hh, mm = (os.getenv("GARMIN_REFRESH_TIME", "05:45").split(":") + ["0"])[:2]
    _sched = BackgroundScheduler(timezone=TZ)
    if garmin.configured():
        _sched.add_job(_safe(garmin.snapshot, "garmin snapshot"), "cron", hour=int(hh), minute=int(mm), id="garmin")
    _sched.add_job(_safe(weather.refresh, "weather"), "cron", hour="*/3", minute=5, id="weather")
    _sched.add_job(_safe(strava.warm_best_efforts, "strava best efforts"), "cron", minute=20, id="strava")
    _sched.start()

    def first_run():  # fill anything missing straight after a (re)deploy
        if not store.doc_get(weather.DOC):
            _safe(weather.refresh, "weather")()
        latest = store.doc_get("garmin/latest") or {}
        if garmin.configured() and latest.get("date") != dt.datetime.now(garmin.TZ).date().isoformat():
            _safe(garmin.snapshot, "garmin snapshot")()
    threading.Thread(target=first_run, daemon=True).start()


def stop() -> None:
    if _sched:
        _sched.shutdown(wait=False)
