# The claude.ai daily tasks

On claude.ai, two scheduled Claude tasks keep the page's saved data fresh each morning (5:40 am Pacific/Auckland):

| Task | Saves | Runs in |
|---|---|---|
| **Refresh KerrChow Fit weather** | `weather/auckland`: AccuWeather daytime forecast, keeping the days of the current week that have passed | The Claude Code session that built the page, because it is the one with the AccuWeather connector. Scheduled tasks that start their own session can't be given connectors on this account. |
| **Refresh KerrChow Fit class details** | `classes/lesmills`: the 7:10 cycle class on Tuesdays and Thursdays | A fresh session each run. It needs no connector, only the Les Mills timetable feed. |

Both use the logic in `tools/daily_refresh.py` (the class task carries its own copy of the class half, because its
session starts without this repository). The tests check that this logic and the self-hosted server agree.

If AccuWeather becomes available to scheduled tasks, or you create the task from the claude.ai routines page with the
connector attached, the combined prompt below does both jobs in one fresh session. `{{SCRIPT}}` stands for the full
text of `tools/daily_refresh.py`.

```
Daily refresh for the KerrChow Fit page (artifact https://claude.ai/artifact/DYEHZS3gxQssUfvTXQfN3T).
Do exactly the steps below and nothing else: don't republish the page, don't touch any other documents, don't
change any settings. Work in your scratchpad directory. Each part is independent: if one fails, still do the other.

SETUP
Save this script as daily_refresh.py in your scratchpad directory, exactly as written:

{{SCRIPT}}

PART 1: WEATHER (documents: collection "weather", doc "auckland")
1. Call the AccuWeather daily forecast tool (widgets-daily-claude) with queryParams
   {"locationKey": "3590462", "unit": "metric", "lang": "en"}  (Auckland Central).
2. Write rows.json from the result, using only the DAYTIME part ("day") of each entry in dailyForecast:
   {"days": [{"date": first 10 characters of the entry's `date`, e.g. "2026-11-10",
              "prob": day.rainProbabilityValue, "mm": day.extended.rainValue, "hrs": day.hoursOfRain,
              "windDir": the direction word in day.extended.wind (e.g. "NNE"),
              "wind": the number in day.extended.wind, "gust": the number in day.extended.gusts,
              "phrase": day.longPhrase, "alerts": the entry's own `alerts` list of ids}, ...one per day],
    "alerts": {"<id>": {"name": alert.name, "when": "<startDate> <startTime> to <endDate> <endTime>" from the
               alert's first affectedAreas entry}, ...one per top-level alert}}
   Copy the numbers exactly; do not work out any other field yourself.
3. Read the saved document with ArtifactData: action "get", collection "weather", doc_id "auckland", with
   out_dir set to your scratchpad directory. Note its version. It is saved as weather/auckland.json there.
4. Run: python3 daily_refresh.py weather rows.json weather/auckland.json weather-out.json
5. Save with ArtifactData: action "set", collection "weather", doc_id "auckland", file_path weather-out.json,
   if_version = the version from step 3 (leave if_version out only if step 3 found no document).

PART 2: LES MILLS CLASSES (documents: collection "classes", doc "lesmills")
1. Download the club timetable, once:
   curl -sS -A "KerrChowFit/1.0 (personal training tracker)" -o cards.json "https://www.lesmills.co.nz/API/TimetablePage/GetTimetableCards?searchClubCodes=01&searchClassCodes=&searchTrainerNames="
   If this fails or the file isn't JSON, skip the rest of part 2: do not retry, and do not ask for network changes.
2. Read the saved document: ArtifactData "get", collection "classes", doc_id "lesmills", out_dir = your
   scratchpad directory. Note its version. It is saved as classes/lesmills.json.
3. Run: python3 daily_refresh.py classes cards.json classes/lesmills.json classes-out.json
   If it prints NO_CLASSES, skip step 4.
4. Save with ArtifactData: action "set", collection "classes", doc_id "lesmills", file_path classes-out.json,
   if_version = the version from step 2 (leave it out only if step 2 found no document).

FINISH
Reply with one line per part: saved (with the dates covered) or failed (with the reason). Then stop.
```
