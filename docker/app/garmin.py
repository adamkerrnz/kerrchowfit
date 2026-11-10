"""Garmin, via Garmin's official Connect Personal API (https://developer.garmin.com/gc-developer-program/personal/).

The owner creates a Personal API key on Garmin Connect Web (Settings -> Personal API Key) and enters it on the
Stats tab (or sets GARMIN_PERSONAL_API_KEY). The key is exchanged for a short-lived bearer token, which reads the
owner's own daily summary, HRV and sleep. Answers are translated into the small shapes the page renders.
"""
import base64
import datetime as dt
import json
import logging
import os
import threading
import time
from zoneinfo import ZoneInfo

import httpx

from . import store
from .errors import ToolError

log = logging.getLogger("garmin")
BASE = os.getenv("GARMIN_PERSONAL_API_BASE_URL", "https://personal.connectapi.garmin.com").rstrip("/")
TOKEN_PATH = "/personalapitoken-service/personal-api/personal-api-key/token"
TOOLS = ["get_user_summary", "get_hrv_data", "get_sleep_summary_range", "get_weekly_intensity_minutes"]
TZ = ZoneInfo(os.getenv("TZ", "Pacific/Auckland"))
TODAY_TTL = 10 * 60  # today's numbers change during the day
PAST_TTL = 6 * 3600  # earlier days settle
KEY_KV, TOKEN_KV = "garmin_api_key", "garmin_token"
_token_lock = threading.Lock()


# ---------- credentials ----------
def api_key() -> str:
    """Key saved from the Stats tab wins over the environment, so it can be rotated without a redeploy."""
    return (store.kv_get(KEY_KV) or os.getenv("GARMIN_PERSONAL_API_KEY", "")).strip()


def key_source() -> str | None:
    return "saved" if store.kv_get(KEY_KV) else "env" if os.getenv("GARMIN_PERSONAL_API_KEY", "").strip() else None


def configured() -> bool:
    return bool(api_key())


def _jwt_exp(token: str) -> float:
    """Expiry from the token's JWT payload; one hour if it can't be read."""
    try:
        part = token.split(".")[1]
        return float(json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))["exp"])
    except Exception:
        return time.time() + 3600


def _exchange(key: str) -> dict:
    try:
        r = httpx.post(BASE + TOKEN_PATH, headers={"Authorization": f"ApiKey {key}", "Accept": "*/*"}, timeout=20)
    except httpx.HTTPError as e:
        raise ToolError("server_unavailable", f"Couldn't reach Garmin: {e}", retryable=True)
    if r.status_code in (400, 401, 403):
        raise ToolError("needs_reauth", "Garmin didn't accept the Personal API key. Create a new one on Garmin Connect Web and enter it on the Stats tab.")
    if r.status_code >= 400:
        raise ToolError("server_unavailable", f"Garmin token request failed (HTTP {r.status_code}).", retryable=True)
    token = r.text.strip()  # the token endpoint returns the bearer JWT as plain text
    return {"token": token, "expires_at": _jwt_exp(token)}


def save_key(key: str) -> None:
    """Validate a key by exchanging it, then keep both. Raises ToolError if Garmin refuses it."""
    key = (key or "").strip()
    if not key:
        raise ToolError("bad_request", "Enter a Garmin Personal API key.")
    tok = _exchange(key)
    store.kv_put(KEY_KV, key)
    store.kv_put(TOKEN_KV, tok)


def clear_key() -> None:
    store.kv_delete(KEY_KV)
    store.kv_delete(TOKEN_KV)


def _token() -> str:
    key = api_key()
    if not key:
        raise ToolError("server_not_connected", "Garmin isn't set up yet. Enter your Personal API key on the Stats tab.")
    with _token_lock:  # the page makes several calls at once; refresh only once
        t = store.kv_get(TOKEN_KV)
        if t and t.get("token") and t.get("expires_at", 0) > time.time() + 300:
            return t["token"]
        t = _exchange(key)
        store.kv_put(TOKEN_KV, t)
        return t["token"]


def _get(path: str, params: dict | None = None):
    try:
        r = httpx.get(BASE + path, params=params, headers={"Authorization": f"Bearer {_token()}", "Accept": "application/json"}, timeout=30)
    except httpx.HTTPError as e:
        raise ToolError("server_unavailable", f"Couldn't reach Garmin: {e}", retryable=True)
    if r.status_code == 401:
        store.kv_delete(TOKEN_KV)
        raise ToolError("needs_reauth", "Garmin rejected the access token. Check the Personal API key on the Stats tab.")
    if r.status_code == 429:
        raise ToolError("rate_limited", "Garmin is rate limiting requests. Try again later.", retryable=True, retry_after_ms=60000)
    if r.status_code >= 400:
        raise ToolError("upstream_error", f"Garmin returned HTTP {r.status_code} for {path}.")
    return r.json() if r.content else None


# ---------- helpers ----------
def _today() -> str:
    return dt.datetime.now(TZ).date().isoformat()


def _cached(key: str, day: str, fn, refresh: bool):
    ttl = TODAY_TTL if day >= _today() else PAST_TTL
    hit = None if refresh else store.cache_get(key, ttl)
    if hit:
        return hit
    value = fn()
    return value, store.cache_put(key, value)


def _list(raw, *keys):
    """Garmin wraps some lists ({"data": [...]}, {"hrvSummaries": [...]}); unwrap to a plain list."""
    for k in keys:
        if isinstance(raw, dict) and isinstance(raw.get(k), list):
            return raw[k]
    return raw if isinstance(raw, list) else []


# ---------- tools (shapes the page renders) ----------
SUMMARY_FIELDS = ("totalSteps", "dailyStepGoal", "restingHeartRate", "lastSevenDaysAvgRestingHeartRate", "averageStressLevel",
                  "bodyBatteryMostRecentValue", "bodyBatteryHighestValue", "bodyBatteryLowestValue", "bodyBatteryAtWakeTime",
                  "moderateIntensityMinutes", "vigorousIntensityMinutes")


def user_summary(date: str) -> dict:
    raw = _get("/usersummary-service/usersummary/daily", {"calendarDate": date}) or {}
    return {k: raw.get(k) for k in SUMMARY_FIELDS}


def hrv(date: str) -> dict:
    s = (_get(f"/hrv-service/hrv/{date}") or {}).get("hrvSummary") or {}
    b = s.get("baseline") or {}
    return {"date": date, "last_night_avg_hrv_ms": s.get("lastNightAvg"), "weekly_avg_hrv_ms": s.get("weeklyAvg"),
            "baseline_balanced_low_ms": b.get("balancedLow"), "baseline_balanced_upper_ms": b.get("balancedUpper"),
            "status": s.get("status"), "feedback": s.get("feedbackPhrase")}


def sleep_range(start: str, end: str) -> dict:
    sleeps = _list(_get("/sleep-service/sleep/dailySleepSummariesByDate", {"startDate": start, "endDate": end}))
    try:  # overnight HRV per night is optional: sleep still shows without it
        hrvs = {x.get("calendarDate"): x.get("lastNightAvg") for x in _list(_get(f"/hrv-service/hrv/daily/{start}/{end}"), "hrvSummaries")}
    except ToolError:
        hrvs = {}
    nights = []
    for d in sleeps:
        d = d.get("dailySleepDTO", d) if isinstance(d, dict) else {}
        if not d.get("sleepTimeSeconds"):
            continue
        score = (d.get("sleepScores") or {}).get("overall") or {}
        nights.append({"date": d.get("calendarDate"), "sleep_seconds": d.get("sleepTimeSeconds"), "sleep_score": score.get("value"),
                       "deep_sleep_seconds": d.get("deepSleepSeconds"), "light_sleep_seconds": d.get("lightSleepSeconds"),
                       "rem_sleep_seconds": d.get("remSleepSeconds"), "awake_seconds": d.get("awakeSleepSeconds"),
                       "avg_overnight_hrv": hrvs.get(d.get("calendarDate"))})
    return {"start_date": start, "end_date": end, "nights": nights}


def intensity_minutes(end: str, weeks: int) -> dict:
    """Weekly totals (Mon-Sun) summed from daily summaries; vigorous minutes count double, as Garmin does."""
    e = dt.date.fromisoformat(end)
    first = e - dt.timedelta(days=e.weekday(), weeks=weeks)
    days = _list(_get("/usersummary-service/v2/dailysummaries", {"startDate": first.isoformat(), "endDate": end}), "data")
    by_week: dict[str, dict] = {}
    for d in days:
        if not isinstance(d, dict) or not d.get("calendarDate"):
            continue
        day = dt.date.fromisoformat(d["calendarDate"][:10])
        im = d.get("intensityMinutes") or {}
        w = by_week.setdefault((day - dt.timedelta(days=day.weekday())).isoformat(), {"moderate": 0, "vigorous": 0, "goal": None})
        w["moderate"] += im.get("moderate") or 0
        w["vigorous"] += im.get("vigorous") or 0
        w["goal"] = im.get("goal") or w["goal"]
    out = [{"week_start": k, "weekly_goal": v["goal"] or 150, "moderate_minutes": v["moderate"], "vigorous_minutes": v["vigorous"],
            "total_minutes": v["moderate"] + 2 * v["vigorous"]} for k, v in by_week.items()]
    out.sort(key=lambda w: w["week_start"], reverse=True)
    return {"end_date": end, "weekly_data": out}


def call(tool: str, inp: dict, refresh: bool):
    """Returns (payload, stored_at_seconds)."""
    inp = inp or {}
    date = inp.get("date") or _today()
    if tool == "get_user_summary":
        return _cached(f"garmin:summary:{date}", date, lambda: user_summary(date), refresh)
    if tool == "get_hrv_data":
        return _cached(f"garmin:hrv:{date}", date, lambda: hrv(date), refresh)
    if tool == "get_sleep_summary_range":
        s, e = inp["start_date"], inp["end_date"]
        return _cached(f"garmin:sleep:{s}:{e}", e, lambda: sleep_range(s, e), refresh)
    if tool == "get_weekly_intensity_minutes":
        end, weeks = inp.get("end_date") or _today(), int(inp.get("weeks") or 4)
        return _cached(f"garmin:im:{end}:{weeks}", end, lambda: intensity_minutes(end, weeks), refresh)
    raise ToolError("not_in_manifest", f"Unknown Garmin tool {tool}")


# ---------- debugging: the untranslated Garmin response ----------
RAW = {
    "summary": lambda d: _get("/usersummary-service/usersummary/daily", {"calendarDate": d}),
    "hrv": lambda d: _get(f"/hrv-service/hrv/{d}"),
    "sleep": lambda d: _get("/sleep-service/sleep/dailySleep", {"date": d}),
    "dailysummaries": lambda d: _get("/usersummary-service/v2/dailysummaries", {"startDate": d, "endDate": d}),
}


def raw(name: str, date: str | None):
    if name not in RAW:
        raise ToolError("bad_request", f"Unknown raw view {name}")
    return RAW[name](date or _today())


# ---------- the morning snapshot the page shows on any device ----------
def plan(today: dt.date) -> dict:
    t = today.isoformat()
    return {
        "summary": ("get_user_summary", {"date": t}),
        "hrv": ("get_hrv_data", {"date": t}),
        "sleep": ("get_sleep_summary_range", {"start_date": (today - dt.timedelta(days=6)).isoformat(), "end_date": t}),
        "im": ("get_weekly_intensity_minutes", {"end_date": t, "weeks": 4}),
    }


def snapshot() -> bool | None:
    """Save today's Garmin data to garmin/latest; None when no key is set, False when every call failed."""
    if not configured():
        return None
    today = dt.datetime.now(TZ).date()
    raw_out, failed = {}, []
    for key, (tool, inp) in plan(today).items():
        try:
            raw_out[key] = call(tool, inp, True)[0]
        except Exception as e:  # keep going: one missing panel shouldn't lose the rest
            failed.append(f"{tool}: {getattr(e, 'message', e)}")
    if not raw_out:
        log.error("Garmin snapshot failed: %s", "; ".join(failed))
        return False
    store.doc_set("garmin/latest", {"v": 2, "date": today.isoformat(), "fetchedAt": int(time.time() * 1000), "source": "scheduled", "raw": raw_out})
    log.info("Garmin snapshot saved for %s%s", today, f" ({len(failed)} failed: {'; '.join(failed)})" if failed else "")
    return True
