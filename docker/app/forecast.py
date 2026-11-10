#!/usr/bin/env python3
"""Builds the page's weather/auckland document from open data. Standard library only.

Forecast: Open-Meteo (free, no key). Warnings: MetService's public CAP alert feed.
The self-hosted server imports the forecast half (app/weather.py); the claude.ai daily task runs this file directly:

  forecast.py links rss.xml                           # print the alert addresses listed in MetService's feed
  forecast.py build om.json caps/ old.json out.json   # forecast + alerts in caps/*.xml + past days of old.json
"""
import datetime as dt
import glob
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

LAT = float(os.getenv("WEATHER_LAT", "-36.8485"))  # Auckland Central
LON = float(os.getenv("WEATHER_LON", "174.7633"))
TZ = os.getenv("TZ") or "Pacific/Auckland"
AREA_NAME = os.getenv("WEATHER_AREA", "Auckland")  # used only when an alert carries no polygon
DAY_START, DAY_END = 7, 19  # daytime hours summarised (start inclusive, end exclusive)
KEEP_PAST_DAYS = 7  # days already gone stay on the page for the rest of their week
ALERT_HOST = "metservice.com"

PHRASES = {
    0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Cloudy", 45: "Fog", 48: "Freezing fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle", 61: "Light rain", 63: "Rain", 65: "Heavy rain",
    66: "Freezing rain", 67: "Heavy freezing rain", 71: "Light snow", 73: "Snow", 75: "Heavy snow",
    80: "Light showers", 81: "Showers", 82: "Heavy showers", 95: "Thunderstorms", 96: "Thunderstorms with hail", 99: "Severe thunderstorms",
}
COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


# ---- forecast (Open-Meteo) ----

def _summary(prob, mm, hrs, wind, gust, deg, code):
    """The fields the page reads for one day."""
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


# ---- warnings (MetService CAP feed) ----

def _strip_ns(root):
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def feed_links(rss_text: str) -> list[str]:
    """Alert addresses in the RSS/Atom feed: https on MetService only, so a tampered feed can't send us elsewhere."""
    root = _strip_ns(ET.fromstring(rss_text))
    out = []
    for el in root.iter("link"):
        url = (el.text or el.get("href") or "").strip()
        u = urlparse(url)
        host = (u.hostname or "").lower()
        is_alert = "/cap/" in u.path and not u.path.rstrip("/").endswith(("/rss", "/atom"))
        if u.scheme == "https" and (host == ALERT_HOST or host.endswith("." + ALERT_HOST)) and is_alert and url not in out:
            out.append(url)
    return out


def _inside(lat, lon, polygon: str) -> bool:
    """Ray casting; a CAP polygon is "lat,lon lat,lon ...". """
    try:
        pts = [tuple(map(float, p.split(","))) for p in polygon.split()]
    except ValueError:
        return False
    hit = False
    for (la1, lo1), (la2, lo2) in zip(pts, pts[1:] + pts[:1]):
        if (lo1 > lon) != (lo2 > lon) and lat < (la2 - la1) * (lon - lo1) / (lo2 - lo1) + la1:
            hit = not hit
    return hit


def _time(text, tz):
    try:
        t = dt.datetime.fromisoformat((text or "").strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return (t if t.tzinfo else t.replace(tzinfo=tz)).astimezone(tz)


def _when(t):
    return f"{t:%a, %b} {t.day} {t.hour % 12 or 12}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"


def parse_alert(cap_text: str, tz, now):
    """One CAP alert as {id, name, when, start, end}, or None if it isn't a live alert covering our point."""
    try:
        root = _strip_ns(ET.fromstring(cap_text))
    except ET.ParseError:
        return None
    if root.tag != "alert" or (root.findtext("status") or "Actual") != "Actual" or (root.findtext("msgType") or "") == "Cancel":
        return None
    infos = root.findall("info")
    info = next((i for i in infos if (i.findtext("language") or "en").lower().startswith("en")), infos[0] if infos else None)
    if info is None:
        return None
    polygons = [p.text for p in info.iter("polygon") if p.text and p.text.strip()]
    if polygons:
        here = any(_inside(LAT, LON, p) for p in polygons)
    else:
        here = any(AREA_NAME.lower() in (a.text or "").lower() for a in info.iter("areaDesc"))
    start = _time(info.findtext("onset") or info.findtext("effective") or root.findtext("sent"), tz)
    end = _time(info.findtext("expires"), tz)
    if not here or not start or not end or end <= start or end <= now:
        return None
    name = (info.findtext("headline") or "").split(" - ")[0].strip() or (info.findtext("event") or "").strip() or "Weather alert"
    ident = re.sub(r"[^A-Za-z0-9]", "", root.findtext("identifier") or "")[-40:]
    if not ident:
        return None
    return {"id": ident, "name": name[:80], "when": f"{_when(start)} to {_when(end)}", "start": start, "end": end}


def attach_alerts(days: dict, alerts: list, tz) -> dict:
    """Tag each day whose daytime hours an alert overlaps; returns the alerts document ({id: {name, when}})."""
    used = {}
    for day, summary in days.items():
        d = dt.date.fromisoformat(day)
        lo = dt.datetime(d.year, d.month, d.day, DAY_START, tzinfo=tz)
        hi = dt.datetime(d.year, d.month, d.day, DAY_END, tzinfo=tz)
        for a in alerts:
            if a["start"] < hi and a["end"] > lo:
                summary["alerts"].append(a["id"])
                used[a["id"]] = {"name": a["name"], "when": a["when"]}
    return used


def build(hourly: dict, cap_texts: list, old: dict, now: dt.datetime) -> dict:
    tz = ZoneInfo(TZ)
    now = now.astimezone(tz)
    new_days = daytime_days(hourly)
    seen, alerts = set(), []
    for text in cap_texts:
        a = parse_alert(text, tz, now)
        if a and a["id"] not in seen:
            seen.add(a["id"])
            alerts.append(a)
    new_alerts = attach_alerts(new_days, alerts, tz)
    days = merge_past(new_days, old.get("days"), now.date().isoformat())
    # Past days keep the warnings they were saved with.
    old_alerts = old.get("alerts") or {}
    kept = {i: old_alerts[i] for d, v in days.items() if d not in new_days for i in v.get("alerts") or [] if i in old_alerts}
    return {"days": days, "alerts": {**kept, **new_alerts}, "fetchedAt": int(now.timestamp() * 1000), "source": "open-meteo"}


# ---- command line ----

def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def main(argv) -> int:
    if len(argv) == 3 and argv[1] == "links":
        try:
            print("\n".join(feed_links(_read(argv[2]))))
        except (OSError, ET.ParseError) as e:
            print(f"no alert feed ({e}); carrying on without warnings", file=sys.stderr)
        return 0
    if len(argv) == 6 and argv[1] == "build":
        om_path, caps_dir, old_path, out_path = argv[2:6]
        try:
            hourly = json.loads(_read(om_path))["hourly"]
            if not daytime_days(hourly):
                raise ValueError("no daytime hours")
        except (OSError, ValueError, KeyError, TypeError) as e:
            print(f"FAILED: the Open-Meteo forecast could not be read ({e}); leave the saved document alone")
            return 2
        old = {}
        if os.path.exists(old_path):
            try:
                old = json.loads(_read(old_path))
                old = old.get("data", old) if isinstance(old, dict) else {}
            except ValueError:
                old = {}
        caps = []
        for path in sorted(glob.glob(os.path.join(caps_dir, "*.xml"))):
            try:
                caps.append(_read(path))
            except (OSError, UnicodeDecodeError):
                pass
        doc = build(hourly, caps, old, dt.datetime.now(dt.timezone.utc))
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)
        names = sorted({a["name"] for a in doc["alerts"].values()})
        print(f"wrote {out_path}: {min(doc['days'])} to {max(doc['days'])}; warnings: {', '.join(names) or 'none'}")
        return 0
    print(__doc__)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv))
