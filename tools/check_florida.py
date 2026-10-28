#!/usr/bin/env python3
"""Format check for June's Florida resident rates file (data/florida.json, schema 1).

  python3 tools/check_florida.py data/florida.json

Written by tools/fetch_florida.py on the owner's AI PC (signed in to a Florida resident NCL
account), never by GitHub Actions. Only numbers, category codes and dates are allowed: any key
outside the lists below fails the check, so nothing personal from the account can reach the
public repo. Run by tools/check_release.py when the file is present.

  saved_at      when the file was written (UTC)
  check         "light" (a few cabins per ship) or "full" (every available cabin)
  checked_on    Eastern date (America/New_York) the latest check started
  sailings[id]  package_id, categories[code] (type, website_fare_pp, florida_fare_pp, off_pp =
                website minus Florida, checked_at, source) and missing (codes a full check
                couldn't read yet)
"""
import datetime as dt
import json
import re
import sys
from zoneinfo import ZoneInfo

MIAMI = ZoneInfo("America/New_York")
SAILING_IDS = {"getaway-2027-06-11", "aura-2027-06-14"}
TOP_KEYS = {"schema_version", "saved_at", "guests", "source", "check", "checked_on", "sailings"}
SAILING_KEYS = {"package_id", "categories", "missing"}
CAT_KEYS = {"type", "website_fare_pp", "florida_fare_pp", "off_pp", "checked_at", "source"}
TYPES = {"INSIDE", "OCEANVIEW", "BALCONY", "MINISUITE", "SUITE", "HAVEN"}
SOURCE = "logged-in NCL account"
CODE = re.compile(r"[A-Z0-9]{2}")


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def utc_time(v):
    try:
        return dt.datetime.strptime(v, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def check(data):
    errors = []
    err = errors.append
    if not isinstance(data, dict):
        return ["the file is not a JSON object"]
    extra = set(data) - TOP_KEYS
    if extra:
        err(f"unexpected keys {sorted(extra)}")
    if data.get("schema_version") != 1:
        err("schema_version must be 1")
    saved = utc_time(data.get("saved_at"))
    if not saved:
        err("saved_at must be a time like 2026-10-27T13:00:00Z")
    if data.get("guests") != 2:
        err("guests must be 2")
    if not isinstance(data.get("source"), str) or len(data["source"]) > 200:
        err("source must be short text")
    if data.get("check") not in ("light", "full"):
        err('check must be "light" or "full"')
    try:
        checked_on = dt.date.fromisoformat(data.get("checked_on"))
    except (TypeError, ValueError):
        checked_on = None
        err("checked_on must be a date like 2026-10-27")
    sailings = data.get("sailings")
    if not isinstance(sailings, dict) or not sailings:
        return errors + ["sailings must be a non-empty object keyed by sailing id"]
    total = 0
    for sid, s in sailings.items():
        p = f"sailing {sid}"
        if sid not in SAILING_IDS:
            err(f"{p}: id must be one of {sorted(SAILING_IDS)}")
        if not isinstance(s, dict):
            err(f"{p}: must be an object")
            continue
        extra = set(s) - SAILING_KEYS
        if extra:
            err(f"{p}: unexpected keys {sorted(extra)}")
        if not re.fullmatch(r"\d+", str(s.get("package_id", ""))):
            err(f"{p}: package_id must be digits")
        missing = s.get("missing")
        if not isinstance(missing, list) or not all(isinstance(c, str) and CODE.fullmatch(c) for c in missing):
            err(f"{p}: missing must be a list of category codes")
        elif missing and data.get("check") != "full":
            err(f"{p}: missing is only used by a full check")
        cats = s.get("categories")
        if not isinstance(cats, dict):
            err(f"{p}: categories must be an object keyed by category code")
            continue
        total += len(cats)
        for code, c in cats.items():
            q = f"{p} category {code}"
            if not CODE.fullmatch(code):
                err(f"{q}: code must be 2 letters or digits")
            if not isinstance(c, dict):
                err(f"{q}: must be an object")
                continue
            extra = set(c) - CAT_KEYS
            if extra:
                err(f"{q}: unexpected keys {sorted(extra)}")
            if c.get("type") not in TYPES:
                err(f"{q}: type must be one of {sorted(TYPES)}")
            w, f, o = c.get("website_fare_pp"), c.get("florida_fare_pp"), c.get("off_pp")
            if not (is_num(w) and w > 0 and is_num(f) and f >= 0 and is_num(o)):
                err(f"{q}: website_fare_pp (above 0), florida_fare_pp and off_pp must be numbers")
            elif abs((w - f) - o) > 0.01:
                err(f"{q}: off_pp must be website_fare_pp minus florida_fare_pp")
            at = utc_time(c.get("checked_at"))
            if not at:
                err(f"{q}: checked_at must be a time like 2026-10-27T13:00:00Z")
            else:
                if saved and at > saved:
                    err(f"{q}: checked_at is after saved_at")
                if checked_on and at.astimezone(MIAMI).date() < checked_on:
                    err(f"{q}: checked_at is before checked_on (an entry from an older check)")
            if c.get("source") != SOURCE:
                err(f"{q}: source must be {SOURCE!r}")
    if not total:
        err("no category in any sailing")
    return errors


def main():
    if len(sys.argv) != 2:
        print("usage: check_florida.py PATH", file=sys.stderr)
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
    n = sum(len(s["categories"]) for s in data["sailings"].values())
    print(f"OK {path}: {data['check']} check on {data['checked_on']}, {n} categories, saved_at {data['saved_at']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
