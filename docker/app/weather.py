"""Daily forecast from Open-Meteo (free, no key), saved as the page's weather/auckland document."""
import logging
import os
import time

import httpx

from . import store

log = logging.getLogger("weather")
LAT = float(os.getenv("WEATHER_LAT", "-36.8485"))  # Auckland Central
LON = float(os.getenv("WEATHER_LON", "174.7633"))
TZ = os.getenv("TZ", "Pacific/Auckland")
DOC = "weather/auckland"  # the page reads this path

PHRASES = {
    0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Cloudy", 45: "Fog", 48: "Freezing fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle", 61: "Light rain", 63: "Rain", 65: "Heavy rain",
    66: "Freezing rain", 67: "Heavy freezing rain", 71: "Light snow", 73: "Snow", 75: "Heavy snow",
    80: "Light showers", 81: "Showers", 82: "Heavy showers", 95: "Thunderstorms", 96: "Thunderstorms with hail", 99: "Severe thunderstorms",
}
COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def _summary(prob, mm, hrs, wind, gust, deg, code):
    """Same fields and thresholds as the page's own summarise() for AccuWeather."""
    prob, mm, hrs, wind, gust = prob or 0, round(mm or 0, 1), round(hrs or 0), round(wind or 0), round(gust or 0)
    rain = ("heavy" if mm >= 10 else "rain") if prob >= 50 and (mm >= 1 or hrs >= 1) else "maybe" if prob >= 30 else "dry"
    windy = "windy" if wind >= 30 or gust >= 50 else "breezy" if wind >= 20 or gust >= 40 else "calm"
    return {"prob": prob, "mm": mm, "hrs": hrs, "wind": wind, "gust": gust,
            "windDir": COMPASS[round((deg or 0) / 22.5) % 16], "rain": rain, "windy": windy,
            "phrase": PHRASES.get(code, ""), "alerts": []}


def refresh() -> None:
    try:
        r = httpx.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": LAT, "longitude": LON, "timezone": TZ, "forecast_days": 10, "wind_speed_unit": "kmh",
            "daily": "weather_code,precipitation_probability_max,precipitation_sum,precipitation_hours,"
                     "wind_speed_10m_max,wind_gusts_10m_max,wind_direction_10m_dominant",
        }, timeout=20)
        r.raise_for_status()
        d = r.json()["daily"]
    except Exception as e:
        log.warning("weather refresh failed: %s", e)
        return
    days = {}
    for i, day in enumerate(d["time"]):
        days[day] = _summary(d["precipitation_probability_max"][i], d["precipitation_sum"][i], d["precipitation_hours"][i],
                             d["wind_speed_10m_max"][i], d["wind_gusts_10m_max"][i], d["wind_direction_10m_dominant"][i],
                             d["weather_code"][i])
    store.doc_set(DOC, {"days": days, "alerts": {}, "fetchedAt": int(time.time() * 1000), "source": "open-meteo"})
    log.info("weather saved for %d days", len(days))
