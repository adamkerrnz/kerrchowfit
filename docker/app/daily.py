"""Daily refresh: everything the scheduled Claude tasks used to do, run by the server itself.

The server runs this once a day at DAILY_REFRESH_TIME. It can also be run by hand, or from the host's cron
instead (set DAILY_REFRESH_TIME= empty to turn the built-in schedule off):

  docker exec kerrchowfit python -m app.daily            # every task
  docker exec kerrchowfit python -m app.daily weather    # just the named ones

Each task is independent: one failing doesn't stop the rest. Exit status is 1 if any task failed.
"""
import logging
import sys
from typing import Callable

from . import garmin, lesmills, strava, weather

log = logging.getLogger("daily")

# name -> job. A job returns True (saved), None (skipped: not set up) or False (failed).
TASKS: dict[str, Callable[[], bool | None]] = {
    "weather": weather.refresh,        # weather/auckland, keeping the past days of this week
    "classes": lesmills.refresh,       # classes/lesmills, Tuesday and Thursday cycle classes
    "garmin": garmin.snapshot,         # garmin/latest
    "strava": strava.warm_best_efforts,  # best-effort cache for the Stats tab
}


def run(names: list[str] | None = None) -> dict[str, str]:
    """Run the named tasks (all by default) and return {name: "ok" | "skipped" | "failed"}."""
    from .jobs import prune  # imported here: jobs imports this module
    tasks = {**TASKS, "prune": lambda: (prune(), True)[1]}
    results = {}
    for name in names or list(tasks):
        if name not in tasks:
            raise ValueError(f"unknown task {name!r}; choose from {', '.join(tasks)}")
        try:
            ok = tasks[name]()
        except Exception:
            log.exception("%s failed", name)
            ok = False
        results[name] = "skipped" if ok is None else "ok" if ok else "failed"
    log.info("daily refresh: %s", ", ".join(f"{k} {v}" for k, v in results.items()))
    return results


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        results = run(argv[1:] or None)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    for name, status in results.items():
        print(f"{name}: {status}")
    return 1 if "failed" in results.values() else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
