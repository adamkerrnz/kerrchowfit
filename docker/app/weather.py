"""Daytime forecast from Open-Meteo (free, no key), saved as the page's weather/auckland document.

Each day is summarised over 7 am to 7 pm, the hours training happens in, to match the claude.ai version
(AccuWeather's daytime forecast). Open-Meteo has no official weather warnings, so `alerts` stays empty.
"""
import datetime as dt
import logging
import os
import time
from zoneinfo import ZoneInfo

import httpx

from . import store

log = logging.getLogger("weather")
LAT = float(os.getenv("WEATHER_LAT", "-36.8485"))  # Auckland Central
LON = float(os.getenv("WEATHER_LON", "174.7633"))
TZ = os.getenv("TZ", "Pacific/Auckland")
DOC = "weather/auckland"  # the page reads this path
DAY_START, DAY_END = 7, 19  # daytime hours summarised (start inclusive, end exclusive)
KEEP_PAST_DAYS = 7  # days already gone stay on the page for the rest of their week

PHRASES = {
    0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Cloudy", 45: "Fog", 48: "Freezing fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle", 61: "Light rain", 63: "Rain", 65: "Heavy rain",
    66: "Freezing rain", 67: "Heavy freezing rain", 71: "Light snow", 73: "Snow", 75: "Heavy snow",
    80: "Light showers", 81: "Showers", 82: "Heavy showers", 95: "Thunderstorms", 96: "Thunderstorms with hail", 99: "Severe thunderstorms",
}
COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def _summary(prob, mm, hrs, wind, gust, deg, code):
    """The fields the page reads from weather/auckland, with the same thresholds the claude.ai weather refresh uses."""
    prob, mm, hrs, wind, gust = round(prob or 0), round(mm or 0, 1), round(hrs or 0, 1), round(wind or 0), round(gust or 0)
    rain = ("heavy" if mm >= 10 else "rain") if prob >= 50 and (mm >= 1 or hrs >= 1) else "maybe" if prob >= 30 else "dry"
    windy = "windy" if wind >= 30 or gust >= 50 else "breezy" if wind >= 20 or gust >= 40 else "calm"
    return {"prob": prob, "mm": mm, "hrs": hrs, "wind": wind, "gust": gust,
            "windDir": COMPASS[round((deg or 0) / 22.5) % 16], "rain": rain, "windy": windy,
            "phrase": PHRASES.get(code, ""), "alerts": []}


def daytime_days(hourly: dict) -> dict:
    """Group Open-Meteo's hourly arrays by date and summarise the daytime hours of each."""
    by_day: dict[str, list[int]] = {}
    for i, stamp in enumerate(hourly["time"]):  # "2026-11-10T07:00", already in the local time zone
        if DAY_START <= int(stamp[11:13]) < DAY_END:
            by_day.setdefault(stamp[:10], []).append(i)
    col = lambda name, idx: [hourly[name][i] for i in idx if hourly[name][i] is not None]
    days = {}
    for day, idx in by_day.items():
        winds = [(hourly["wind_speed_10m"][i] or 0, i) for i in idx]
        top_wind, top_i = max(winds) if winds else (0, idx[0])
        rain = col("precipitation", idx)
        codes = col("weather_code", idx)
        days[day] = _summary(
            max(col("precipitation_probability", idx), default=0),
            sum(rain),
            sum(1 for v in rain if v >= 0.1),
            top_wind,
            max(col("wind_gusts_10m", idx), default=0),
            hourly["wind_direction_10m"][top_i],
            max(codes, default=None),  # WMO codes rise with severity, so the highest is the day's worst spell
        )
    return days


def merge_past(new_days: dict, old_days: dict, today: str) -> dict:
    """Keep the last week of days that have dropped out of the forecast, so earlier days of this week still show."""
    cutoff = (dt.date.fromisoformat(today) - dt.timedelta(days=KEEP_PAST_DAYS)).isoformat()
    kept = {d: v for d, v in (old_days or {}).items() if cutoff <= d < today and d not in new_days}
    return {**kept, **new_days}


def refresh() -> None:
    try:
        r = httpx.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": LAT, "longitude": LON, "timezone": TZ, "forecast_days": 10, "wind_speed_unit": "kmh",
            "hourly": "weather_code,precipitation_probability,precipitation,wind_speed_10m,wind_gusts_10m,wind_direction_10m",
        }, timeout=20)
        r.raise_for_status()
        days = daytime_days(r.json()["hourly"])
    except Exception as e:
        log.warning("weather refresh failed: %s", e)
        return
    today = dt.datetime.now(ZoneInfo(TZ)).date().isoformat()
    old = store.doc_get(DOC) or {}
    days = merge_past(days, old.get("days"), today)
    store.doc_set(DOC, {"days": days, "alerts": {}, "fetchedAt": int(time.time() * 1000), "source": "open-meteo"})
    log.info("weather saved for %d days", len(days))
