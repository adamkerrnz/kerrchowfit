"""Strava, via Strava's own API (your own Strava API app; no Strava subscription needed).

Answers the three tools the page calls, in the same shapes the claude.ai Strava connector returns:
list_activities, get_active_streak, get_athlete_best_efforts.
"""
import datetime as dt
import logging
import os
import secrets
import threading
import time
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx

from . import store
from .errors import ToolError

log = logging.getLogger("strava")
TOOLS = ["list_activities", "get_active_streak", "get_athlete_best_efforts"]
API = "https://www.strava.com/api/v3"
TOKEN_URL = "https://www.strava.com/oauth/token"
TZ = ZoneInfo(os.getenv("TZ", "Pacific/Auckland"))
ACTS_TTL = 15 * 60  # seconds the activity list is reused
DETAIL_BUDGET = 30  # uncached activity detail/stream fetches per best-efforts call (rate limit: 100 / 15 min)


# ---------- auth ----------
APP_KV = "strava_app"


def _app() -> tuple[str, str]:
    """Strava API app (client ID + secret): saved from the Stats tab, else from the environment."""
    a = store.kv_get(APP_KV)
    return (a["client_id"], a["client_secret"]) if a else _env_app()


def app_source() -> str | None:
    return "saved" if store.kv_get(APP_KV) else "env" if all(_env_app()) else None


def _env_app():
    return os.getenv("STRAVA_CLIENT_ID", "").strip(), os.getenv("STRAVA_CLIENT_SECRET", "").strip()


def save_app(client_id: str, client_secret: str) -> None:
    """Keep a new API app; tokens from a different app no longer work, so they are dropped."""
    client_id, client_secret = str(client_id or "").strip(), str(client_secret or "").strip()
    if not client_id.isdigit() or not client_secret:
        raise ToolError("bad_request", "Enter the numeric Client ID and the Client Secret from strava.com/settings/api.")
    if _app() != (client_id, client_secret):
        store.kv_delete("strava_tokens")
    store.kv_put(APP_KV, {"client_id": client_id, "client_secret": client_secret})


def clear() -> None:
    store.kv_delete(APP_KV)
    store.kv_delete("strava_tokens")


def _tokens():
    t = store.kv_get("strava_tokens")
    if not t and os.getenv("STRAVA_REFRESH_TOKEN"):
        t = {"refresh_token": os.getenv("STRAVA_REFRESH_TOKEN").strip(), "access_token": None, "expires_at": 0}
    return t


def configured() -> bool:
    return app_configured() and bool(_tokens())


def app_configured() -> bool:
    return all(_app())


STATE_TTL = 10 * 60  # seconds a sign-in may take


def new_state() -> str:
    """A one-time value sent to Strava and checked on the way back, so only a sign-in started here is accepted."""
    state = secrets.token_urlsafe(24)
    store.kv_put(f"strava:state:{state}", True)
    return state


def check_state(state: str | None) -> bool:
    if not state:
        return False
    key = f"strava:state:{state}"
    hit = store.cache_get(key, STATE_TTL)
    store.kv_delete(key)  # single use
    return bool(hit)


def auth_url(redirect_uri: str, state: str) -> str:
    return "https://www.strava.com/oauth/authorize?" + urlencode({
        "client_id": _app()[0], "redirect_uri": redirect_uri, "response_type": "code",
        "approval_prompt": "auto", "scope": "read,activity:read_all", "state": state,
    })


def _creds() -> dict:
    cid, sec = _app()
    return {"client_id": cid, "client_secret": sec}


def _save(d: dict) -> None:
    store.kv_put("strava_tokens", {k: d[k] for k in ("access_token", "refresh_token", "expires_at")})


def exchange_code(code: str) -> None:
    r = httpx.post(TOKEN_URL, data={**_creds(), "code": code, "grant_type": "authorization_code"}, timeout=20)
    r.raise_for_status()
    _save(r.json())


_token_lock = threading.Lock()


def _access_token() -> str:
    # One refresh at a time: the page makes three calls at once, and they would otherwise all refresh together.
    with _token_lock:
        return _access_token_locked()


def _access_token_locked() -> str:
    t = _tokens()
    if not t:
        raise ToolError("server_not_connected", "Strava isn't connected yet. Connect Strava on the Stats tab.")
    if t.get("access_token") and t.get("expires_at", 0) > time.time() + 60:
        return t["access_token"]
    r = httpx.post(TOKEN_URL, data={**_creds(), "grant_type": "refresh_token", "refresh_token": t["refresh_token"]}, timeout=20)
    if r.status_code in (400, 401):
        raise ToolError("needs_reauth", "Strava sign-in has expired. Connect Strava on the Stats tab.")
    r.raise_for_status()
    d = r.json()
    _save(d)
    return d["access_token"]


def _get(path: str, params: dict | None = None):
    try:
        r = httpx.get(API + path, params=params, headers={"Authorization": f"Bearer {_access_token()}"}, timeout=30)
    except httpx.HTTPError as e:
        raise ToolError("server_unavailable", f"Couldn't reach Strava: {e}", retryable=True)
    if r.status_code == 401:
        raise ToolError("needs_reauth", "Strava refused the sign-in. Connect Strava on the Stats tab.")
    if r.status_code == 429:
        raise ToolError("server_unavailable", "Strava's rate limit was reached. Try again in 15 minutes.")
    if r.status_code >= 500:
        raise ToolError("server_unavailable", "Strava is having problems right now.", retryable=True)
    if r.status_code >= 400:
        raise ToolError("tool_error", f"Strava returned {r.status_code} for {path}.")
    return r.json()


# ---------- activities ----------
def _monday(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())


def _year_of_activities(refresh: bool):
    """Raw Strava summary activities from the Monday 53 weeks ago, cached for 15 minutes."""
    since = _monday(dt.datetime.now(TZ).date()) - dt.timedelta(weeks=53)
    key = f"strava:acts:{since.isoformat()}"
    hit = store.cache_get(key, 60 if refresh else ACTS_TTL)  # a refresh still reuses data under a minute old
    if hit:
        return hit
    after = int(dt.datetime.combine(since, dt.time(), TZ).timestamp())
    acts, page = [], 1
    while page <= 10:
        batch = _get("/athlete/activities", {"after": after, "per_page": 100, "page": page})
        acts += batch
        if len(batch) < 100:
            break
        page += 1
    stored = store.cache_put(key, acts)
    return acts, stored


def _pace(seconds: float, km: float) -> str:
    s = seconds / km
    return f"{int(s // 60)}:{int(s % 60):02d} /km"


def _map(a: dict) -> dict:
    km = (a.get("distance") or 0) / 1000
    sport = a.get("sport_type") or a.get("type") or "Workout"
    s = {
        "moving_time": a.get("moving_time") or 0,
        "distance": round(km, 2),
        "pr_count": a.get("pr_count") or 0,
        "achievement_count": a.get("achievement_count") or 0,
    }
    if a.get("suffer_score") is not None:
        s["relative_effort"] = round(a["suffer_score"])
    if "Run" in sport and km > 0.2 and s["moving_time"]:
        s["avg_pace_display"] = _pace(s["moving_time"], km)
    # start_date_local is local wall time but carries a misleading "Z"; the page reads it as local time.
    return {"id": str(a.get("id")), "name": a.get("name"), "sport_type": sport,
            "start_local": (a.get("start_date_local") or "").rstrip("Z"), "summary": s}


def list_activities(inp: dict, refresh: bool):
    acts, stored = _year_of_activities(refresh)
    start = str(inp.get("range_start") or "")[:19]
    mapped = [_map(a) for a in acts]
    if start:
        mapped = [m for m in mapped if m["start_local"] >= start]
    mapped.sort(key=lambda m: m["start_local"], reverse=True)
    first = int(inp.get("first") or 100)
    offset = int(inp.get("after") or 0)
    page = mapped[offset:offset + first]
    more = offset + first < len(mapped)
    return {"activities": page, "has_next_page": more, "end_cursor": str(offset + first) if more else None,
            "value_units": {"distance": "km"}}, stored


def get_active_streak(inp: dict, refresh: bool):
    acts, stored = _year_of_activities(refresh)
    weeks = {}
    for a in acts:
        d = dt.date.fromisoformat((a.get("start_date_local") or "")[:10])
        weeks[_monday(d)] = weeks.get(_monday(d), 0) + 1
    this_week = _monday(dt.datetime.now(TZ).date())
    pending = weeks.get(this_week, 0) == 0
    wk, length = this_week - dt.timedelta(weeks=1) if pending else this_week, 0
    count = 0
    while weeks.get(wk, 0) > 0:
        length += 1
        count += weeks[wk]
        wk -= dt.timedelta(weeks=1)
    # valid_activity_count is the number of activities across the whole streak, as the claude.ai connector reports it.
    return {"length": length, "streak_status": "Pending" if pending else "Ongoing",
            "valid_activity_count": count}, stored


# ---------- best efforts (last 12 months) ----------
def _best_5k(a: dict, budget: list) -> int | None:
    key = f"strava:be5k:{a['id']}"
    hit = store.cache_get(key, None)
    if hit:
        return hit[0] if hit[0] >= 0 else None
    if budget[0] <= 0:
        return None
    budget[0] -= 1
    detail = _get(f"/activities/{a['id']}")
    times = [b["elapsed_time"] for b in detail.get("best_efforts") or [] if str(b.get("name", "")).lower() == "5k"]
    best = min(times) if times else -1
    store.cache_put(key, best)
    return best if best >= 0 else None


def _best_20min_power(a: dict, budget: list) -> int | None:
    key = f"strava:p20:{a['id']}"
    hit = store.cache_get(key, None)
    if hit:
        return hit[0] if hit[0] >= 0 else None
    if budget[0] <= 0:
        return None
    budget[0] -= 1
    streams = _get(f"/activities/{a['id']}/streams", {"keys": "watts,time", "key_by_type": "true"})
    watts = (streams.get("watts") or {}).get("data") or []
    times = (streams.get("time") or {}).get("data") or []
    best = -1
    if watts and times and len(watts) == len(times) and times[-1] >= 1200:
        per_sec, j = [], 0  # resample to one value per second, carrying the last reading through gaps
        for t in range(times[-1] + 1):
            while j + 1 < len(times) and times[j + 1] <= t:
                j += 1
            per_sec.append(watts[j] or 0)
        window = sum(per_sec[:1200])
        top = window
        for i in range(1200, len(per_sec)):
            window += per_sec[i] - per_sec[i - 1200]
            top = max(top, window)
        best = round(top / 1200)
    store.cache_put(key, best)
    return best if best >= 0 else None


def get_athlete_best_efforts(inp: dict, refresh: bool):
    acts, stored = _year_of_activities(False)
    budget = [DETAIL_BUDGET]
    efforts = []
    runs = [a for a in acts if "Run" in (a.get("sport_type") or "") and (a.get("distance") or 0) >= 5000]
    best = None
    for a in sorted(runs, key=lambda a: a.get("start_date_local", ""), reverse=True):
        v = _best_5k(a, budget)
        if v is not None and (best is None or v < best[0]):
            best = (v, a)
    if best:
        efforts.append({"best_effort_type": "Fastest5k", "value": best[0], "sport": "Run", "date": best[1]["start_date_local"][:10]})
    rides = [a for a in acts if a.get("device_watts") and (a.get("moving_time") or 0) >= 1200]
    best = None
    for a in sorted(rides, key=lambda a: a.get("start_date_local", ""), reverse=True):
        v = _best_20min_power(a, budget)
        if v is not None and (best is None or v > best[0]):
            best = (v, a)
    if best:
        efforts.append({"best_effort_type": "GreatestPower20min", "value": best[0], "sport": "Ride", "date": best[1]["start_date_local"][:10]})
    if budget[0] <= 0:
        log.info("best efforts: fetch budget used up; the rest are filled in on later calls")
    # all_time is false here: these are the best in the last 12 months, and the page labels them that way.
    return {"efforts": efforts, "all_time": False, "window_months": 12}, stored


def warm_best_efforts() -> None:
    """Background job: fill the best-effort cache a little at a time within Strava's rate limit."""
    if configured():
        try:
            get_athlete_best_efforts({}, False)
        except ToolError as e:
            log.warning("best efforts warm-up: %s", e.message)


def call(tool: str, inp: dict, refresh: bool):
    return {"list_activities": list_activities, "get_active_streak": get_active_streak,
            "get_athlete_best_efforts": get_athlete_best_efforts}[tool](inp or {}, refresh)
