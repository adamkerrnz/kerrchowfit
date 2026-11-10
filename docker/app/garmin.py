"""Garmin Connect, via the unofficial `garminconnect` library (Garmin has no public API for individuals).

Answers the eight tools the page calls, translated into the same "curated" shapes the Garmin Connect
MCP server returns, so the page's Garmin section works unchanged. Garmin's raw field names are not
documented and can change; GET /api/debug/garmin/<tool> shows the raw response if a field goes missing.
"""
import datetime as dt
import logging
import os
import threading
from pathlib import Path
from zoneinfo import ZoneInfo

from . import store
from .errors import ToolError

log = logging.getLogger("garmin")
TOOLS = ["get_user_summary", "get_training_readiness", "get_hrv_data", "get_sleep_summary_range",
         "get_training_status", "get_training_load_balance", "get_vo2max_trend", "get_weekly_intensity_minutes"]
TOKENS = os.getenv("GARMIN_TOKENS", "/data/garmin-tokens")
TZ = ZoneInfo(os.getenv("TZ", "Pacific/Auckland"))
TODAY_TTL = 10 * 60  # today's numbers change during the day
PAST_TTL = 6 * 3600  # earlier days settle

_lock = threading.Lock()
_client = None


def _has_tokens() -> bool:
    p = Path(TOKENS)
    return p.is_dir() and any(p.iterdir())


def configured() -> bool:
    return _has_tokens() or bool(os.getenv("GARMIN_EMAIL") and os.getenv("GARMIN_PASSWORD"))


def client():
    """Signed-in Garmin client: saved tokens first, else email + password from the environment."""
    global _client
    from garminconnect import Garmin
    with _lock:
        if _client is not None:
            return _client
        if _has_tokens():
            try:
                g = Garmin()
                g.login(TOKENS)
                _client = g
                return g
            except Exception as e:  # tokens expired or unreadable: fall through to a password login
                log.warning("saved Garmin tokens didn't work: %s", e)
        email, password = os.getenv("GARMIN_EMAIL"), os.getenv("GARMIN_PASSWORD")
        if not (email and password):
            raise ToolError("server_not_connected", "Garmin isn't signed in. Set GARMIN_EMAIL and GARMIN_PASSWORD, or run python -m app.garmin_login in the container.")
        g = Garmin(email, password, return_on_mfa=True)
        res = g.login()
        if isinstance(res, tuple) and res and res[0] == "needs_mfa":
            raise ToolError("needs_reauth", "Garmin asked for a 2-step verification code. Run python -m app.garmin_login in the container console.")
        Path(TOKENS).mkdir(parents=True, exist_ok=True)
        g.garth.dump(TOKENS)
        _client = g
        return g


def _g(method: str, *args):
    """Call a garminconnect method, turning its errors into the page's error codes."""
    global _client
    from garminconnect import (GarminConnectAuthenticationError, GarminConnectConnectionError,
                               GarminConnectTooManyRequestsError)
    try:
        return getattr(client(), method)(*args)
    except ToolError:
        raise
    except GarminConnectAuthenticationError as e:
        _client = None
        raise ToolError("needs_reauth", f"Garmin sign-in failed: {e}")
    except GarminConnectTooManyRequestsError:
        raise ToolError("server_unavailable", "Garmin is rate limiting requests. Try again later.")
    except GarminConnectConnectionError as e:
        raise ToolError("server_unavailable", f"Couldn't reach Garmin Connect: {e}", retryable=True)


def _today() -> str:
    return dt.datetime.now(TZ).date().isoformat()


def _cached(key: str, day: str, fn, refresh: bool):
    ttl = TODAY_TTL if day >= _today() else PAST_TTL
    hit = None if refresh else store.cache_get(key, ttl)
    if hit:
        return hit
    value = fn()
    return value, store.cache_put(key, value)


def _days(start: str, end: str):
    d, e = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    while d <= e:
        yield d.isoformat()
        d += dt.timedelta(days=1)


# ---------- translations into the MCP server's shapes ----------
def _readiness_entry(x: dict) -> dict:
    rec = x.get("recoveryTime")  # minutes
    return {
        "date": x.get("calendarDate"), "timestamp": x.get("timestampLocal") or x.get("timestamp"),
        "context": x.get("inputContext"), "level": x.get("level"), "score": x.get("score"), "feedback": x.get("feedbackShort"),
        "sleep_score": x.get("sleepScore"),
        "sleep_factor_percent": x.get("sleepScoreFactorPercent"), "sleep_factor_feedback": x.get("sleepScoreFactorFeedback"),
        "recovery_time_hours": round(rec / 60, 1) if rec is not None else None,
        "recovery_factor_percent": x.get("recoveryTimeFactorPercent"), "recovery_factor_feedback": x.get("recoveryTimeFactorFeedback"),
        "training_load_factor_percent": x.get("acwrFactorPercent"), "training_load_feedback": x.get("acwrFactorFeedback"),
        "acute_load": x.get("acuteLoad"),
        "hrv_factor_percent": x.get("hrvFactorPercent"), "hrv_factor_feedback": x.get("hrvFactorFeedback"),
        "hrv_weekly_avg": x.get("hrvWeeklyAverage"),
        "stress_history_factor_percent": x.get("stressHistoryFactorPercent"), "stress_history_feedback": x.get("stressHistoryFactorFeedback"),
        "sleep_history_factor_percent": x.get("sleepHistoryFactorPercent"), "sleep_history_feedback": x.get("sleepHistoryFactorFeedback"),
    }


def training_readiness(date: str):
    raw = _g("get_training_readiness", date) or []
    items = raw if isinstance(raw, list) else [raw]
    return [_readiness_entry(x) for x in items if isinstance(x, dict)]


def hrv(date: str):
    raw = _g("get_hrv_data", date) or {}
    s = raw.get("hrvSummary") or {}
    b = s.get("baseline") or {}
    return {"date": date, "last_night_avg_hrv_ms": s.get("lastNightAvg"), "last_night_5min_high_hrv_ms": s.get("lastNight5MinHigh"),
            "weekly_avg_hrv_ms": s.get("weeklyAvg"), "baseline_balanced_low_ms": b.get("balancedLow"),
            "baseline_balanced_upper_ms": b.get("balancedUpper"), "baseline_low_upper_ms": b.get("lowUpper"),
            "status": s.get("status"), "feedback": s.get("feedbackPhrase")}


def _sleep_night(date: str):
    raw = _g("get_sleep_data", date) or {}
    d = raw.get("dailySleepDTO") or {}
    if not d.get("sleepTimeSeconds"):
        return None
    score = ((d.get("sleepScores") or {}).get("overall") or {})
    return {"date": date, "sleep_seconds": d.get("sleepTimeSeconds"), "sleep_score": score.get("value"),
            "sleep_score_qualifier": score.get("qualifierKey"), "deep_sleep_seconds": d.get("deepSleepSeconds"),
            "light_sleep_seconds": d.get("lightSleepSeconds"), "rem_sleep_seconds": d.get("remSleepSeconds"),
            "awake_seconds": d.get("awakeSleepSeconds"), "resting_heart_rate_bpm": raw.get("restingHeartRate"),
            "avg_overnight_hrv": raw.get("avgOvernightHrv")}


def sleep_range(start: str, end: str, refresh: bool):
    nights, oldest = [], None
    for day in _days(start, end):
        night, stored = _cached(f"garmin:sleep:{day}", day, lambda day=day: _sleep_night(day), refresh and day == end)
        oldest = stored if oldest is None else min(oldest, stored)
        if night:
            nights.append(night)
    return {"start_date": start, "end_date": end, "nights": nights}, oldest


def _status_raw(date: str, refresh: bool):
    return _cached(f"garmin:status:{date}", date, lambda: _g("get_training_status", date) or {}, refresh)


def _pick_device(d: dict):
    return next(iter(d.items()), (None, {})) if isinstance(d, dict) else (None, {})


def training_status(date: str, refresh: bool):
    raw, stored = _status_raw(date, refresh)
    latest = ((raw.get("mostRecentTrainingStatus") or {}).get("latestTrainingStatusData")) or {}
    dev, t = _pick_device(latest)
    acwr = t.get("acuteTrainingLoadDTO") or {}
    vo2 = raw.get("mostRecentVO2Max") or {}
    gen, cyc = vo2.get("generic") or {}, vo2.get("cycling") or {}
    return {"date": date, "reporting_device_id": dev, "training_status": t.get("trainingStatus"),
            "training_status_feedback": t.get("trainingStatusFeedbackPhrase"), "sport": t.get("sport"),
            "vo2_max": gen.get("vo2MaxValue"), "vo2_max_precise": gen.get("vo2MaxPreciseValue"),
            "cycling_vo2_max": cyc.get("vo2MaxValue"), "cycling_vo2_max_precise": cyc.get("vo2MaxPreciseValue"),
            "acute_load": acwr.get("dailyTrainingLoadAcute"), "chronic_load": acwr.get("dailyTrainingLoadChronic"),
            "load_ratio": acwr.get("dailyAcuteChronicWorkloadRatio"), "acwr_status": acwr.get("acwrStatus"),
            "optimal_chronic_load_min": acwr.get("minTrainingLoadChronic"),
            "optimal_chronic_load_max": acwr.get("maxTrainingLoadChronic")}, stored


def load_balance(date: str, refresh: bool):
    raw, stored = _status_raw(date, refresh)
    m = ((raw.get("mostRecentTrainingLoadBalance") or {}).get("metricsTrainingLoadBalanceDTOMap")) or {}
    _, d = _pick_device(m)

    def band(name: str):
        load, lo, hi = d.get(f"monthlyLoad{name}"), d.get(f"monthlyLoad{name}TargetMin"), d.get(f"monthlyLoad{name}TargetMax")
        if load is None:
            return None
        status = "below" if lo is not None and load < lo else "above" if hi is not None and load > hi else "within"
        return {"load": round(load, 1), "target_min": lo, "target_max": hi, "status": status}

    out = {"date": date, "feedback": d.get("trainingBalanceFeedbackPhrase")}
    for key, name in (("aerobic_low", "AerobicLow"), ("aerobic_high", "AerobicHigh"), ("anaerobic", "Anaerobic")):
        b = band(name)
        if b:
            out[key] = b
    return out, stored


def _vo2_day(date: str):
    raw = _g("get_max_metrics", date) or []
    item = raw[0] if isinstance(raw, list) and raw else raw if isinstance(raw, dict) else {}
    return {"generic": (item.get("generic") or {}).get("vo2MaxPreciseValue"),
            "cycling": (item.get("cycling") or {}).get("vo2MaxPreciseValue")}


def vo2_trend(start: str, end: str, refresh: bool):
    """Daily VO2 max, kept in the database so each day is only fetched once (the first call backfills ~8 weeks)."""
    days = list(_days(start, end))
    per_day, oldest = {}, None
    today = _today()
    for day in days:
        hit = store.cache_get(f"garmin:vo2:{day}", TODAY_TTL if day >= today else None)
        if hit and day < today:
            # A past day is final only if it was fetched after that day ended; otherwise fetch it once more.
            day_end = dt.datetime.combine(dt.date.fromisoformat(day) + dt.timedelta(days=1), dt.time(), TZ).timestamp()
            if hit[1] < day_end:
                hit = None
        if hit and not (refresh and day == end):
            v, stored = hit
        else:
            v = _vo2_day(day)
            stored = store.cache_put(f"garmin:vo2:{day}", v)
        per_day[day] = v
        oldest = stored if oldest is None else min(oldest, stored)
    sport = "cycling" if any(v.get("cycling") for v in per_day.values()) else "generic"
    trend, last = [], None
    for day in days:
        v = per_day[day].get(sport)
        if v is not None:
            last = v
            trend.append({"date": day, "vo2_max": v})
        elif last is not None:
            trend.append({"date": day, "vo2_max": last, "carried_forward": True})
    first_v = trend[0]["vo2_max"] if trend else None
    last_v = trend[-1]["vo2_max"] if trend else None
    return {"start_date": start, "end_date": end, "sport": "cycling" if sport == "cycling" else "running",
            "first_vo2_max": first_v, "latest_vo2_max": last_v,
            "change": round(last_v - first_v, 1) if trend else None, "trend": trend}, oldest


def intensity_minutes(end: str, weeks: int):
    e = dt.date.fromisoformat(end)
    start = (e - dt.timedelta(days=e.weekday()) - dt.timedelta(weeks=weeks)).isoformat()
    raw = _g("get_weekly_intensity_minutes", start, end) or []
    out = []
    for w in raw if isinstance(raw, list) else []:
        mod, vig = w.get("moderateValue") or 0, w.get("vigorousValue") or 0
        out.append({"week_start": w.get("calendarDate"), "weekly_goal": w.get("weeklyGoal") or 150,
                    "moderate_minutes": mod, "vigorous_minutes": vig, "total_minutes": mod + 2 * vig})
    out.sort(key=lambda w: w["week_start"] or "", reverse=True)
    return {"end_date": end, "weekly_data": out}


# ---------- dispatch ----------
def call(tool: str, inp: dict, refresh: bool):
    inp = inp or {}
    date = inp.get("date") or _today()
    if tool == "get_user_summary":
        return _cached(f"garmin:summary:{date}", date, lambda: _g("get_user_summary", date), refresh)
    if tool == "get_training_readiness":
        return _cached(f"garmin:readiness:{date}", date, lambda: training_readiness(date), refresh)
    if tool == "get_hrv_data":
        return _cached(f"garmin:hrv:{date}", date, lambda: hrv(date), refresh)
    if tool == "get_sleep_summary_range":
        return sleep_range(inp["start_date"], inp["end_date"], refresh)
    if tool == "get_training_status":
        return training_status(date, refresh)
    if tool == "get_training_load_balance":
        return load_balance(date, refresh)
    if tool == "get_vo2max_trend":
        return vo2_trend(inp["start_date"], inp["end_date"], refresh)
    if tool == "get_weekly_intensity_minutes":
        end = inp.get("end_date") or _today()
        weeks = int(inp.get("weeks") or 4)
        return _cached(f"garmin:im:{end}:{weeks}", end, lambda: intensity_minutes(end, weeks), refresh)
    raise ToolError("not_in_manifest", f"Unknown Garmin tool {tool}")


RAW = {  # for GET /api/debug/garmin/<name>: the untranslated Garmin response
    "summary": "get_user_summary", "readiness": "get_training_readiness", "hrv": "get_hrv_data",
    "sleep": "get_sleep_data", "status": "get_training_status", "maxmetrics": "get_max_metrics",
}


def raw(name: str, date: str | None):
    if name not in RAW:
        raise ToolError("bad_request", f"Unknown raw view {name}")
    return _g(RAW[name], date or _today())


# ---------- the morning snapshot the page shows on any device ----------
def snapshot() -> None:
    today = dt.datetime.now(TZ).date()
    t = today.isoformat()
    plan = {
        "summary": ("get_user_summary", {"date": t}),
        "readiness": ("get_training_readiness", {"date": t}),
        "hrv": ("get_hrv_data", {"date": t}),
        "sleep": ("get_sleep_summary_range", {"start_date": (today - dt.timedelta(days=6)).isoformat(), "end_date": t}),
        "status": ("get_training_status", {"date": t}),
        "focus": ("get_training_load_balance", {"date": t}),
        "vo2": ("get_vo2max_trend", {"start_date": (today - dt.timedelta(days=55)).isoformat(), "end_date": t}),
        "im": ("get_weekly_intensity_minutes", {"end_date": t, "weeks": 4}),
    }
    raw_out, failed = {}, []
    for key, (tool, inp) in plan.items():
        try:
            raw_out[key] = call(tool, inp, True)[0]
        except Exception as e:  # keep going: one missing panel shouldn't lose the rest
            failed.append(f"{tool}: {getattr(e, 'message', e)}")
    if not raw_out:
        log.error("Garmin snapshot failed: %s", "; ".join(failed))
        return
    import time
    store.doc_set("garmin/latest", {"v": 1, "date": t, "fetchedAt": int(time.time() * 1000), "source": "scheduled", "raw": raw_out})
    log.info("Garmin snapshot saved for %s%s", t, f" ({len(failed)} failed: {'; '.join(failed)})" if failed else "")
