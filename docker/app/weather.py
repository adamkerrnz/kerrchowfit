"""Daytime forecast from Open-Meteo (free, no key), saved as the page's weather/auckland document.

The summarising lives in app/forecast.py, shared with the claude.ai daily task.
Open-Meteo has no official weather warnings, so `alerts` stays empty.
"""
import datetime as dt
import logging
import time
from zoneinfo import ZoneInfo

import httpx

from . import store
from .forecast import COMPASS, DAY_END, DAY_START, KEEP_PAST_DAYS, LAT, LON, PHRASES, TZ, _summary, daytime_days, merge_past  # noqa: F401

log = logging.getLogger("weather")
DOC = "weather/auckland"  # the page reads this path


def refresh() -> bool:
    """Fetch and save the forecast; False if the weather service could not be reached."""
    try:
        r = httpx.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": LAT, "longitude": LON, "timezone": TZ, "forecast_days": 10, "wind_speed_unit": "kmh",
            "hourly": "weather_code,precipitation_probability,precipitation,wind_speed_10m,wind_gusts_10m,wind_direction_10m",
        }, timeout=20)
        r.raise_for_status()
        days = daytime_days(r.json()["hourly"])
    except Exception as e:
        log.warning("weather refresh failed: %s", e)
        return False
    today = dt.datetime.now(ZoneInfo(TZ)).date().isoformat()
    old = store.doc_get(DOC) or {}
    days = merge_past(days, old.get("days"), today)
    store.doc_set(DOC, {"days": days, "alerts": {}, "fetchedAt": int(time.time() * 1000), "source": "open-meteo"})
    log.info("weather saved for %d days", len(days))
    return True
