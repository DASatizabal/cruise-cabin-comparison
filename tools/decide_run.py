#!/usr/bin/env python3
"""First step of the "Refresh prices" workflow: decide what this run does.

  python3 tools/decide_run.py --event schedule
  python3 tools/decide_run.py --event workflow_dispatch --source timer
  python3 tools/decide_run.py --event schedule --now 2026-10-13T10:20:00Z   (test with a fixed clock)

"Today" is the date in Miami (America/New_York, the time zone, so daylight saving time is
handled), never the UTC date and never a fixed UTC-5 or UTC-4 offset. Why: on 2026-10-12 a
manual run at 9:35 PM Eastern saved prices at 2026-10-13T01:36Z; by UTC date that counted as
Oct 13, so the Cloudflare timer runs and GitHub's scheduled runs on Oct 13 all skipped the
prices job and nothing was refreshed that day (NOTES.md, "Eastern dates").

Timed runs skip work that is already done today. Timed runs are GitHub's scheduled runs
(10:17, 14:47 and 19:37 UTC) and runs started by the Cloudflare Worker in
tools/refresh-trigger/ (workflow_dispatch with source "timer", 10:20 and 15:05 UTC):
  - prices and counts both saved today (Eastern date of saved_at): skip everything
  - prices saved today, counts not: skip the price job, run only counts
  - otherwise: run both
Manual runs (source "manual") always run both, on main or on a branch (choose the count mode
in the "Run workflow" form). Branch test runs (a push to the development branch) run prices
only: counts are skipped, so a push costs about 26 NCL calls, not about 165 with a full counts
sweep (owner's request, 2026-10-15).
From the first sail date on (Jun 11, 2027, Eastern), every run skips everything, manual runs
too: the Getaway has sailed, Options 1 and 3 are gone, and NCL no longer lists it, so the
page keeps the last prices it had.

Writes "prices=true|false" and "counts=true|false" to GITHUB_OUTPUT (or prints them when
run by hand), and shows the case that applied as a notice on the run's summary page and
in the run summary.
A missing or unreadable file counts as not refreshed today.
"""
import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_prices import SAILINGS, MIAMI  # noqa: E402   (MIAMI = ZoneInfo("America/New_York"))

# The refresh stops from the first sail date (the Getaway, Jun 11, 2027).
STOP_DATE = min(dt.date.fromisoformat(s["depart"]) for s in SAILINGS)


def parse_utc(text):
    return dt.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


def eastern_date(when):
    """The calendar date in Miami for a UTC time (EDT or EST, whichever applies that day)."""
    return when.astimezone(MIAMI).date()


def saved_date(path):
    try:
        with open(path, encoding="utf-8") as f:
            saved = json.load(f)["saved_at"]
        return eastern_date(parse_utc(saved)), saved
    except Exception as e:
        return None, f"unreadable ({e.__class__.__name__})"


def decide(event, prices_path, counts_path, today, source="", stop=STOP_DATE):
    prices_day, prices_saved = saved_date(prices_path)
    counts_day, counts_saved = saved_date(counts_path)
    seen = f"prices saved_at {prices_saved}, counts saved_at {counts_saved}, today (Eastern) {today}"
    if today >= stop:
        return False, False, f"Skipped: the Getaway sails on {stop}, so there is nothing left to refresh ({seen})."
    if event == "workflow_dispatch" and source == "timer":
        seen = "started by the Cloudflare timer, " + seen
    elif event == "push":
        return True, False, f"Prices only: branch test runs fetch prices; counts run on a branch only from a manual run ({seen})."
    elif event != "schedule":
        kind = "manual" if event == "workflow_dispatch" else event
        return True, True, f"Full run: {kind} runs always fetch prices and counts ({seen})."
    prices_done = prices_day == today
    counts_done = counts_day == today
    if prices_done and counts_done:
        return False, False, f"Skipped: prices and counts were both already refreshed today ({seen})."
    if prices_done:
        return False, True, f"Counts only: prices were already refreshed today, counts were not ({seen})."
    return True, True, f"Full run: prices were not refreshed today yet ({seen})."


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--event", required=True)
    ap.add_argument("--source", default="", help="workflow_dispatch input: manual or timer")
    ap.add_argument("--prices", default="data/prices.json")
    ap.add_argument("--counts", default="data/counts.json")
    ap.add_argument("--now", help="a UTC time like 2026-10-13T10:20:00Z, for tests; default is now")
    args = ap.parse_args()
    today = eastern_date(parse_utc(args.now) if args.now else dt.datetime.now(dt.timezone.utc))
    prices, counts, why = decide(args.event, args.prices, args.counts, today, args.source)
    print(f"::notice title=Refresh decision::{why}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"### {why.split(':')[0]}\n\n{why}\n")
    lines = f"prices={'true' if prices else 'false'}\ncounts={'true' if counts else 'false'}\n"
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(lines)
    else:
        print(lines, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
