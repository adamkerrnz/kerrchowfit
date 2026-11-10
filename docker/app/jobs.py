"""Background schedule (replaces the scheduled Claude tasks): Garmin and the class timetable each morning, weather every 3 hours."""
import datetime as dt
import logging
import os
import threading

from apscheduler.schedulers.background import BackgroundScheduler

from . import garmin, lesmills, store, strava, weather

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
    # Always scheduled: the key can be entered on the Stats tab after start-up; the job skips itself until then.
    _sched.add_job(_safe(garmin.snapshot, "garmin snapshot"), "cron", hour=int(hh), minute=int(mm), id="garmin")
    _sched.add_job(_safe(weather.refresh, "weather"), "cron", hour="*/3", minute=5, id="weather")
    _sched.add_job(_safe(strava.warm_best_efforts, "strava best efforts"), "cron", minute=20, id="strava")
    if lesmills.enabled():
        _sched.add_job(_safe(lesmills.refresh, "les mills timetable"), "cron", hour=4, minute=50, id="lesmills")
    _sched.add_job(_safe(prune, "cache clean-up"), "cron", hour=3, minute=30, id="prune")
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
