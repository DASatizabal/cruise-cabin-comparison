#!/usr/bin/env python3
"""Format check for the DoubleUp watch file (data/offers.json, schema 1).

  python3 tools/check_offers.py data/offers.json

Written daily by tools/fetch_offers.py in the "refresh" job. Public NCL text, dates and codes
only: any key outside the lists below fails the check. Run by tools/check_release.py when the
file is present.

  saved_at      when the file was written (UTC)
  checked_on    Eastern date (America/New_York) of this run
  source        NCL's CruiseNext page
  read_ok       whether this run could read the page (false: the previous state is kept)
  warnings      text list
  doubleup      listed, title, text, types, min_days, min_months, read_on (Eastern date of the
                last run that read the page), since (Eastern date this state was first seen);
                null only before the first successful read
  last_change   kind (started, appeared, ended, changed), on, old_listed, old_text, new_listed,
                new_text, marker, reported; null before the first successful read
"""
import datetime as dt
import json
import re
import sys

TOP_KEYS = {"schema_version", "saved_at", "checked_on", "source", "read_ok", "warnings", "doubleup", "last_change"}
DU_KEYS = {"listed", "title", "text", "types", "min_days", "min_months", "read_on", "since"}
CHANGE_KEYS = {"kind", "on", "old_listed", "old_text", "new_listed", "new_text", "marker", "reported"}
TYPES = ["STUDIO", "INSIDE", "OCEANVIEW", "BALCONY", "MINISUITE", "SUITE", "HAVEN"]
SOURCE = "https://www.ncl.com/cruise-deals/cruisenext"
MAX_TEXT = 600


def date(v):
    try:
        return dt.date.fromisoformat(v) if isinstance(v, str) and len(v) == 10 else None
    except ValueError:
        return None


def short_text(v):
    return isinstance(v, str) and 0 < len(v) <= MAX_TEXT and "\n" not in v and "\r" not in v


def check(data):
    errors = []
    err = errors.append
    if not isinstance(data, dict):
        return ["the file is not a JSON object"]
    extra = set(data) - TOP_KEYS
    if extra:
        err(f"unexpected keys {sorted(extra)}")
    missing = TOP_KEYS - set(data)
    if missing:
        err(f"missing keys {sorted(missing)}")
    if data.get("schema_version") != 1:
        err("schema_version must be 1")
    try:
        dt.datetime.strptime(data.get("saved_at"), "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        err("saved_at must be a time like 2026-10-29T10:21:00Z")
    checked_on = date(data.get("checked_on"))
    if not checked_on:
        err("checked_on must be a date like 2026-10-29")
    if data.get("source") != SOURCE:
        err(f"source must be {SOURCE}")
    read_ok = data.get("read_ok")
    if not isinstance(read_ok, bool):
        err("read_ok must be true or false")
    warnings = data.get("warnings")
    if not isinstance(warnings, list) or not all(short_text(w) for w in warnings):
        err("warnings must be a list of short one-line texts")
        warnings = []
    if read_ok is False and not warnings:
        err("read_ok false needs a warning saying why")

    du = data.get("doubleup")
    if du is None:
        if read_ok:
            err("doubleup can only be null when the page could not be read")
    elif not isinstance(du, dict):
        err("doubleup must be an object or null")
    else:
        extra, missing = set(du) - DU_KEYS, DU_KEYS - set(du)
        if extra:
            err(f"doubleup: unexpected keys {sorted(extra)}")
        if missing:
            err(f"doubleup: missing keys {sorted(missing)}")
        listed = du.get("listed")
        if not isinstance(listed, bool):
            err("doubleup.listed must be true or false")
        if listed:
            if not short_text(du.get("title")) or not short_text(du.get("text")):
                err("doubleup: a listed banner needs a title and text (one line, at most 600 characters)")
            types = du.get("types")
            if types is not None and (not isinstance(types, list) or not types
                                      or any(t not in TYPES for t in types) or len(set(types)) != len(types)):
                err(f"doubleup.types must be null or a list of {TYPES}")
            if types is None and not any("cabin types" in w for w in warnings):
                err("doubleup.types null needs the matching warning")
            days, months = du.get("min_days"), du.get("min_months")
            for k, v in (("min_days", days), ("min_months", months)):
                if v is not None and (not isinstance(v, int) or isinstance(v, bool) or not 0 < v <= 730):
                    err(f"doubleup.{k} must be null or a whole number from 1 to 730")
            if days is not None and months is not None:
                err("doubleup: only one of min_days and min_months")
            if days is None and months is None and not any("before sailing" in w for w in warnings):
                err("doubleup: no time before sailing needs the matching warning")
        elif listed is False:
            for k in ("title", "text", "types", "min_days", "min_months"):
                if du.get(k) is not None:
                    err(f"doubleup.{k} must be null when no banner is listed")
        read_on, since = date(du.get("read_on")), date(du.get("since"))
        if not read_on or not since:
            err("doubleup.read_on and doubleup.since must be dates like 2026-10-29")
        elif since > read_on:
            err("doubleup.since is after doubleup.read_on")
        if read_on and checked_on:
            if read_ok and read_on != checked_on:
                err("doubleup.read_on must be checked_on when the page was read")
            if read_on > checked_on:
                err("doubleup.read_on is after checked_on")

    ch = data.get("last_change")
    if ch is None:
        if du is not None:
            err("last_change is missing although a state was read")
    elif not isinstance(ch, dict):
        err("last_change must be an object or null")
    else:
        extra, missing = set(ch) - CHANGE_KEYS, CHANGE_KEYS - set(ch)
        if extra:
            err(f"last_change: unexpected keys {sorted(extra)}")
        if missing:
            err(f"last_change: missing keys {sorted(missing)}")
        kind = ch.get("kind")
        if kind not in ("started", "appeared", "ended", "changed"):
            err("last_change.kind must be started, appeared, ended or changed")
        if not date(ch.get("on")):
            err("last_change.on must be a date like 2026-10-29")
        if not isinstance(ch.get("marker"), str) or not re.fullmatch(r"doubleup-[0-9a-f]{12}", ch["marker"]):
            err("last_change.marker must look like doubleup-0123456789ab")
        if not isinstance(ch.get("reported"), bool):
            err("last_change.reported must be true or false")
        for side in ("old", "new"):
            listed, text = ch.get(f"{side}_listed"), ch.get(f"{side}_text")
            if side == "old" and kind == "started":
                if listed is not None or text is not None:
                    err("last_change: a started change has no old state")
                continue
            if not isinstance(listed, bool):
                err(f"last_change.{side}_listed must be true or false")
            elif listed and not short_text(text):
                err(f"last_change.{side}_text must be the banner text")
            elif not listed and text is not None:
                err(f"last_change.{side}_text must be null when no banner was listed")
        if kind == "appeared" and not (ch.get("old_listed") is False and ch.get("new_listed") is True):
            err("last_change: appeared means old_listed false and new_listed true")
        if kind == "ended" and not (ch.get("old_listed") is True and ch.get("new_listed") is False):
            err("last_change: ended means old_listed true and new_listed false")
        if kind == "changed" and not (ch.get("old_listed") and ch.get("new_listed") and ch.get("old_text") != ch.get("new_text")):
            err("last_change: changed means both listed with different text")
        if isinstance(du, dict) and (ch.get("new_listed"), ch.get("new_text")) != (du.get("listed"), du.get("text")):
            err("last_change's new state must be the saved doubleup state")
    return errors


def main():
    if len(sys.argv) != 2:
        print("usage: check_offers.py PATH", file=sys.stderr)
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
    du = data["doubleup"]
    state = "not read yet" if du is None else ("DoubleUp listed" if du["listed"] else "no DoubleUp banner")
    print(f"OK {path}: {state}, checked {data['checked_on']}, read_ok {data['read_ok']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
