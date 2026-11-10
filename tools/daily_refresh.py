#!/usr/bin/env python3
"""Builds the two documents the claude.ai daily task saves to the KerrChow Fit artifact.

Standard library only, because the scheduled Claude session that runs it starts with nothing installed.
The self-hosted server does the same work in docker/app/weather.py and docker/app/lesmills.py; the tests
check that both give the same answers.

  daily_refresh.py weather  rows.json  old.json  out.json
  daily_refresh.py classes  cards.json old.json  out.json

`old.json` is the document as currently saved (or a path that doesn't exist, the first time).
"""
import datetime as dt
import json
import os
import sys
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Pacific/Auckland")
KEEP_PAST_DAYS = 7  # days already gone stay on the page for the rest of their week


def _load(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    return d.get("data", d) if isinstance(d, dict) else {}


def _keep_past(new_days, old_days, today):
    cutoff = (dt.date.fromisoformat(today) - dt.timedelta(days=KEEP_PAST_DAYS)).isoformat()
    kept = {d: v for d, v in (old_days or {}).items() if cutoff <= d < today and d not in new_days}
    return {**kept, **new_days}


# ---------- weather ----------
def weather_day(row):
    """One day's fields from the AccuWeather daytime forecast, with the labels the page shows."""
    prob, mm, hrs = row.get("prob") or 0, row.get("mm") or 0, row.get("hrs") or 0
    wind, gust = row.get("wind") or 0, row.get("gust") or 0
    rain = ("heavy" if mm >= 10 else "rain") if prob >= 50 and (mm >= 1 or hrs >= 1) else "maybe" if prob >= 30 else "dry"
    windy = "windy" if wind >= 30 or gust >= 50 else "breezy" if wind >= 20 or gust >= 40 else "calm"
    return {"prob": prob, "mm": mm, "hrs": hrs, "wind": wind, "gust": gust, "windDir": row.get("windDir") or "",
            "rain": rain, "windy": windy, "phrase": row.get("phrase") or "", "alerts": list(row.get("alerts") or [])}


def build_weather(rows, old, today, now_iso):
    days = _keep_past({r["date"]: weather_day(r) for r in rows.get("days", [])}, old.get("days"), today)
    alerts = dict(rows.get("alerts") or {})
    for day in days.values():  # keep the wording of warnings that earlier days of the week still point at
        for a in day.get("alerts") or []:
            if a not in alerts and a in (old.get("alerts") or {}):
                alerts[a] = old["alerts"][a]
    return {"fetchedAt": now_iso, "source": "AccuWeather daily forecast, Auckland Central (3590462)", "days": days, "alerts": alerts}


# ---------- Les Mills classes ----------
CYCLE = {"SPRINT": "Les Mills Sprint", "LES MILLS SPRINT": "Les Mills Sprint", "RPM": "RPM", "THE TRIP": "The Trip"}
ORDER = list(CYCLE)


def _clock(hhmm, add_minutes=0):
    t = dt.datetime.strptime(hhmm, "%H:%M") + dt.timedelta(minutes=add_minutes)
    return f"{t.hour % 12 or 12}:{t.minute:02d}", "AM" if t.hour < 12 else "PM"


def _span(start, mins):
    (a, am), (b, bm) = _clock(start), _clock(start, mins)
    return f"{a}–{b} {bm}" if am == bm else f"{a} {am}–{b} {bm}"


def _instructor(card):
    names = [str(card.get(k) or "").strip(" .") for k in ("mainInstructorName", "secondaryInstructorName")]
    return " + ".join(n for n in names if n)


def pick_classes(cards, start="07:10"):
    """{date: class details} for every Tuesday and Thursday in the feed that has a cycle class at `start`."""
    by_day = {}
    for c in cards:
        name = str(c.get("className") or "").strip().upper()
        if name not in CYCLE:
            continue
        try:
            day = dt.datetime.strptime(c["startDate"], "%d %b %Y").date()
        except (KeyError, ValueError):
            continue
        if day.weekday() in (1, 3):
            by_day.setdefault(day.isoformat(), []).append({**c, "_name": name})
    out = {}
    for day, items in by_day.items():
        main = sorted((c for c in items if c.get("startTime") == start), key=lambda c: ORDER.index(c["_name"]))
        if not main:
            continue
        m = main[0]
        mins = int(m.get("durationMins") or 0)
        entry = {"time": _span(start, mins), "name": CYCLE[m["_name"]], "mins": mins,
                 "studio": str(m.get("siteName") or "").strip(), "instructor": _instructor(m)}
        earlier = sorted((c for c in items if "06:00" <= str(c.get("startTime") or "") < start), key=lambda c: c["startTime"])
        if earlier:
            e = earlier[0]
            clock, ampm = _clock(e["startTime"])
            who = _instructor(e)
            entry["alt"] = (f"{CYCLE[e['_name']]} at {clock} {ampm} ({int(e.get('durationMins') or 0)} min)"
                            f"{' with ' + who if who else ''}, {str(e.get('siteName') or '').strip()}")
        out[day] = entry
    return out


def build_classes(feed, old, today, now_ms):
    data = feed.get("responseData") or {}
    days = pick_classes(data.get("cards") or [])
    if not days:
        return None
    club = next((c.get("clubName") for c in data.get("clubs") or [] if c.get("crmClubCode") == "01"), None)
    return {"days": _keep_past(days, old.get("days"), today), "club": club, "fetchedAt": now_ms, "source": "lesmills.co.nz"}


def main(argv):
    kind, src, old_path, out_path = argv[1:5]
    with open(src, encoding="utf-8") as f:
        src_data = json.load(f)
    old = _load(old_path)
    now = dt.datetime.now(dt.timezone.utc)
    today = now.astimezone(TZ).date().isoformat()
    if kind == "weather":
        doc = build_weather(src_data, old, today, now.strftime("%Y-%m-%dT%H:%M:%SZ"))
    elif kind == "classes":
        doc = build_classes(src_data, old, today, int(now.timestamp() * 1000))
        if doc is None:
            print("NO_CLASSES: the feed had no 7:10 cycle class on a Tuesday or Thursday; leave the saved document alone")
            return 2
    else:
        print(__doc__)
        return 1
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    print(f"wrote {out_path}: days {', '.join(sorted(doc['days']))}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
