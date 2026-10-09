#!/usr/bin/env python3
"""First step of the "Refresh prices" workflow: decide what this run does.

  python3 tools/decide_run.py --event schedule

Scheduled runs (10:17, 14:47 and 19:37 UTC) skip work that is already done today:
  - prices and counts both saved today (UTC date of saved_at): skip everything
  - prices saved today, counts not: skip the price job, run only counts
  - otherwise: run both
Manual runs and branch test runs always run both.

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


def saved_date(path):
    try:
        with open(path, encoding="utf-8") as f:
            saved = json.load(f)["saved_at"]
        return dt.datetime.strptime(saved, "%Y-%m-%dT%H:%M:%SZ").date(), saved
    except Exception as e:
        return None, f"unreadable ({e.__class__.__name__})"


def decide(event, prices_path, counts_path, today):
    prices_day, prices_saved = saved_date(prices_path)
    counts_day, counts_saved = saved_date(counts_path)
    seen = f"prices saved_at {prices_saved}, counts saved_at {counts_saved}, today (UTC) {today}"
    if event != "schedule":
        return True, True, f"Full run: {event} runs always fetch prices and counts ({seen})."
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
    ap.add_argument("--prices", default="data/prices.json")
    ap.add_argument("--counts", default="data/counts.json")
    ap.add_argument("--today", help="YYYY-MM-DD, for tests; default is today's UTC date")
    args = ap.parse_args()
    today = dt.date.fromisoformat(args.today) if args.today else dt.datetime.now(dt.timezone.utc).date()
    prices, counts, why = decide(args.event, args.prices, args.counts, today)
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
