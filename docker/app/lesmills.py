"""The morning cycle class on Les Mills days, from the club's public timetable, saved as classes/lesmills.

This reads the same data feed the Les Mills website loads its timetable page from. It is not an official API:
it can change or stop without notice, so everything here fails quietly and the page falls back to its built-in
class details. One request a day. Set LESMILLS_CLUB to an empty value to turn it off.
"""
import datetime as dt
import logging
import os
import time
from zoneinfo import ZoneInfo

import httpx

from . import store

log = logging.getLogger("lesmills")
CLUB = os.getenv("LESMILLS_CLUB", "01").strip()  # 01 = Auckland City
START = os.getenv("LESMILLS_TIME", "07:10").strip()  # preferred class start, 24-hour
TZ = os.getenv("TZ", "Pacific/Auckland")
DOC = "classes/lesmills"  # the page reads this path
URL = "https://www.lesmills.co.nz/API/TimetablePage/GetTimetableCards"
# Cycle classes in order of preference, with the name the page shows.
CYCLE = {"SPRINT": "Les Mills Sprint", "LES MILLS SPRINT": "Les Mills Sprint", "RPM": "RPM", "THE TRIP": "The Trip"}
ORDER = list(CYCLE)
KEEP_PAST_DAYS = 7


def enabled() -> bool:
    return bool(CLUB)


def _clock(hhmm: str, add_minutes: int = 0) -> tuple[str, str]:
    """('7:10', 'AM') for '07:10', optionally shifted by a number of minutes."""
    t = dt.datetime.strptime(hhmm, "%H:%M") + dt.timedelta(minutes=add_minutes)
    return f"{t.hour % 12 or 12}:{t.minute:02d}", "AM" if t.hour < 12 else "PM"


def _span(start: str, mins: int) -> str:
    (a, am), (b, bm) = _clock(start), _clock(start, mins)
    return f"{a}–{b} {bm}" if am == bm else f"{a} {am}–{b} {bm}"


def _instructor(card: dict) -> str:
    names = [str(card.get(k) or "").strip(" .") for k in ("mainInstructorName", "secondaryInstructorName")]
    return " + ".join(n for n in names if n)


def pick_classes(cards: list[dict], start: str = START) -> dict:
    """{date: class details} for every Tuesday and Thursday in the feed that has a cycle class at `start`."""
    by_day: dict[str, list[dict]] = {}
    for c in cards:
        name = str(c.get("className") or "").strip().upper()
        if name not in CYCLE:
            continue  # other classes, and the VIRTUAL versions
        try:
            day = dt.datetime.strptime(c["startDate"], "%d %b %Y").date()
        except (KeyError, ValueError):
            continue
        if day.weekday() in (1, 3):  # Tuesday, Thursday
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


def refresh() -> None:
    if not enabled():
        return
    try:
        r = httpx.get(URL, params={"searchClubCodes": CLUB, "searchClassCodes": "", "searchTrainerNames": ""},
                      headers={"User-Agent": "KerrChowFit/1.0 (personal training tracker)"}, timeout=30)
        r.raise_for_status()
        data = r.json().get("responseData") or {}
        days = pick_classes(data.get("cards") or [])
        club = next((c.get("clubName") for c in data.get("clubs") or [] if c.get("crmClubCode") == CLUB), None)
    except Exception as e:
        log.warning("Les Mills timetable refresh failed: %s", e)
        return
    if not days:
        log.warning("Les Mills timetable had no %s cycle classes on Tuesday or Thursday; keeping what was saved", START)
        return
    today = dt.datetime.now(ZoneInfo(TZ)).date()
    cutoff = (today - dt.timedelta(days=KEEP_PAST_DAYS)).isoformat()
    old = (store.doc_get(DOC) or {}).get("days") or {}
    kept = {d: v for d, v in old.items() if cutoff <= d < today.isoformat() and d not in days}
    store.doc_set(DOC, {"days": {**kept, **days}, "club": club, "fetchedAt": int(time.time() * 1000), "source": "lesmills.co.nz"})
    log.info("Les Mills classes saved for %s", ", ".join(sorted(days)))
