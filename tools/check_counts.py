#!/usr/bin/env python3
"""Format check for the cabin counts file (data/counts.json).

  python3 tools/check_counts.py data/counts.new.json

Separate from tools/check_prices.py on purpose: a bad counts file must never block a price
publish. The counts job runs this before it replaces data/counts.json; the page also ignores
a counts file it can't use.
"""
import datetime as dt
import json
import sys

EXPECTED_SAILINGS = {"getaway-2027-06-11", "aura-2027-06-14"}
GUEST_KEYS = {"2", "3", "4", "5"}
GUARANTEE_CODES = {"IX", "OX", "BX", "MX"}
LOCATIONS = {"forward", "midship", "aft"}


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_time(v):
    try:
        dt.datetime.strptime(v, "%Y-%m-%dT%H:%M:%SZ")
        return True
    except (TypeError, ValueError):
        return False


def check(data):
    errors = []
    err = errors.append
    if not isinstance(data, dict):
        return ["the file is not a JSON object"]
    if data.get("schema_version") != 1:
        err("schema_version must be 1")
    for k in ("saved_at", "last_full_sweep"):
        if not is_time(data.get(k)):
            err(f"{k} must look like 2026-10-09T10:17:00Z")
    if data.get("mode") not in ("full", "light"):
        err("mode must be full or light")
    if is_time(data.get("saved_at")) and is_time(data.get("last_full_sweep")) and data["last_full_sweep"] > data["saved_at"]:
        err("last_full_sweep can't be after saved_at")
    for k in ("calls", "rechecked", "pause_seconds"):
        if not is_int(data.get(k)) or data[k] < 0:
            err(f"{k} must be a whole number")
    if not isinstance(data.get("unreliable"), list):
        err("unreliable must be a list")

    sailings = data.get("sailings")
    if not isinstance(sailings, dict):
        return errors + ["sailings must be an object keyed by sailing id"]
    for sid in sorted(EXPECTED_SAILINGS - set(sailings)):
        err(f"sailing {sid} is missing")
    for sid in sorted(set(sailings) - EXPECTED_SAILINGS):
        err(f"unknown sailing {sid}")
    for sid, cats in sailings.items():
        if not isinstance(cats, dict):
            err(f"{sid}: categories must be an object keyed by code")
            continue
        for code, c in cats.items():
            p = f"{sid} {code}"
            if code in GUARANTEE_CODES:
                err(f"{p}: Guarantee cabins have no count")
            decks = c.get("open_decks")
            if decks is not None and (not isinstance(decks, list) or not decks or not all(is_int(d) for d in decks)):
                err(f"{p}: open_decks must be a list of deck numbers or null")
            locs = c.get("open_locations")
            if locs is not None and (not isinstance(locs, list) or not locs or not set(locs) <= LOCATIONS):
                err(f"{p}: open_locations must be a list of forward, midship, aft or null")
            bg = c.get("by_guests")
            if not isinstance(bg, dict) or not set(bg) <= GUEST_KEYS:
                err(f"{p}: by_guests must be keyed by 2, 3, 4, 5")
                continue
            for g, e in bg.items():
                ep = f"{p} at {g} guests"
                left = e.get("cabins_left")
                if not isinstance(e.get("reliable"), bool):
                    err(f"{ep}: reliable must be true or false")
                elif e["reliable"]:
                    if not is_int(left) or left < 1:
                        err(f"{ep}: a reliable count must be a positive whole number")
                    if e.get("why") is not None:
                        err(f"{ep}: a reliable count has no why")
                else:
                    if left is not None:
                        err(f"{ep}: an unreliable count must be null")
                    if not isinstance(e.get("why"), str) or not e["why"]:
                        err(f"{ep}: an unreliable count needs a why")
                if not is_time(e.get("checked_at")):
                    err(f"{ep}: checked_at must be a time")
                elif is_time(data.get("saved_at")) and e["checked_at"] > data["saved_at"]:
                    err(f"{ep}: checked_at can't be after saved_at")
    return errors


def main():
    if len(sys.argv) != 2:
        print("usage: check_counts.py PATH", file=sys.stderr)
        return 2
    path = sys.argv[1]
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"FAIL {path}: cannot read JSON ({e})")
        return 1
    errors = check(data)
    if errors:
        print(f"FAIL {path}: {len(errors)} problem(s)")
        for e in errors:
            print("  - " + e)
        return 1
    print(f"OK {path}: {data['mode']} mode, saved_at {data['saved_at']}, last full sweep {data['last_full_sweep']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
