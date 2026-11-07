#!/usr/bin/env python3
"""Format check for the CruiseNext offer watch file (data/offers.json, schema 2; schema 1 too).

  python3 tools/check_offers.py data/offers.json          a new file: must be schema 2
  python3 tools/check_offers.py --any-schema data/offers.json

Written daily by tools/fetch_offers.py in the "refresh" job. Public NCL text, dates and codes
only: any key outside the lists below fails the check. Run by tools/check_release.py when the
file is present (schema 1 is accepted there until the first refresh on main after 5.3.0).

  saved_at      when the file was written (UTC)
  checked_on    Eastern date (America/New_York) of this run
  source        NCL's CruiseNext page
  read_ok       whether this run could read the page (false: the previous state is kept)
  warnings      text list
  multi_credit  listed, title, name (like "TripleUp!"), credits (2 to 4, null with a warning),
                text, types, min_days, min_months, read_on (Eastern date of the last run that
                read the page), since (Eastern date this state was first seen); null only
                before the first successful read. Schema 1: "doubleup", without name and credits.
  last_change   kind (started, appeared, ended, changed), on, old_listed, old_name, old_credits,
                old_text, new_listed, new_name, new_credits, new_text, marker, reported; null
                before the first successful read. Schema 1: without the names and credits.
"""
import datetime as dt
import json
import re
import sys

TOP_KEYS = {1: {"schema_version", "saved_at", "checked_on", "source", "read_ok", "warnings", "doubleup", "last_change"},
            2: {"schema_version", "saved_at", "checked_on", "source", "read_ok", "warnings", "multi_credit", "last_change"}}
OFFER_KEY = {1: "doubleup", 2: "multi_credit"}
OFFER_KEYS = {1: {"listed", "title", "text", "types", "min_days", "min_months", "read_on", "since"}}
OFFER_KEYS[2] = OFFER_KEYS[1] | {"name", "credits"}
CHANGE_KEYS = {1: {"kind", "on", "old_listed", "old_text", "new_listed", "new_text", "marker", "reported"}}
CHANGE_KEYS[2] = CHANGE_KEYS[1] | {"old_name", "old_credits", "new_name", "new_credits"}
MARKER = {1: r"doubleup-[0-9a-f]{12}", 2: r"(?:doubleup|offer)-[0-9a-f]{12}"}
NAME = re.compile(r"(?:double|triple|quadruple|quad)\s*-?\s*up\s*!?", re.I)
TYPES = ["STUDIO", "INSIDE", "OCEANVIEW", "BALCONY", "MINISUITE", "SUITE", "HAVEN"]
SOURCE = "https://www.ncl.com/cruise-deals/cruisenext"
MAX_TEXT = 600
MAX_NAME = 40


def date(v):
    try:
        return dt.date.fromisoformat(v) if isinstance(v, str) and len(v) == 10 else None
    except ValueError:
        return None


def short_text(v):
    return isinstance(v, str) and 0 < len(v) <= MAX_TEXT and "\n" not in v and "\r" not in v


def credits_ok(v):
    return isinstance(v, int) and not isinstance(v, bool) and 2 <= v <= 4


def name_ok(v):
    return isinstance(v, str) and len(v) <= MAX_NAME and NAME.fullmatch(v) is not None


def check(data, any_schema=True):
    """Problems with the file, or []. any_schema False: only schema 2 (a file written today)."""
    errors = []
    err = errors.append
    if not isinstance(data, dict):
        return ["the file is not a JSON object"]
    v = data.get("schema_version")
    if v not in ((1, 2) if any_schema else (2,)):
        return ["schema_version must be 2" + (" (or 1, written before 5.3.0)" if any_schema else "")]
    key = OFFER_KEY[v]
    extra = set(data) - TOP_KEYS[v]
    if extra:
        err(f"unexpected keys {sorted(extra)}")
    missing = TOP_KEYS[v] - set(data)
    if missing:
        err(f"missing keys {sorted(missing)}")
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

    du = data.get(key)
    if du is None:
        if read_ok:
            err(f"{key} can only be null when the page could not be read")
    elif not isinstance(du, dict):
        err(f"{key} must be an object or null")
    else:
        extra, missing = set(du) - OFFER_KEYS[v], OFFER_KEYS[v] - set(du)
        if extra:
            err(f"{key}: unexpected keys {sorted(extra)}")
        if missing:
            err(f"{key}: missing keys {sorted(missing)}")
        listed = du.get("listed")
        if not isinstance(listed, bool):
            err(f"{key}.listed must be true or false")
        if listed:
            if not short_text(du.get("title")) or not short_text(du.get("text")):
                err(f"{key}: a listed banner needs a title and text (one line, at most 600 characters)")
            if v == 2:
                if not name_ok(du.get("name")):
                    err(f"{key}.name must be the offer's name, like DoubleUp!, TripleUp! or QuadUp!")
                elif isinstance(du.get("title"), str) and du["name"] not in du["title"]:
                    err(f"{key}.name must be part of the title")
                c = du.get("credits")
                if c is not None and not credits_ok(c):
                    err(f"{key}.credits must be null or a whole number from 2 to 4")
                if c is None and read_ok and not any("how many credits" in w for w in warnings):
                    err(f"{key}.credits null needs the matching warning")
            types = du.get("types")
            if types is not None and (not isinstance(types, list) or not types
                                      or any(t not in TYPES for t in types) or len(set(types)) != len(types)):
                err(f"{key}.types must be null or a list of {TYPES}")
            if types is None and read_ok is not False and not any("cabin types" in w for w in warnings):
                err(f"{key}.types null needs the matching warning")
            days, months = du.get("min_days"), du.get("min_months")
            for k, val in (("min_days", days), ("min_months", months)):
                if val is not None and (not isinstance(val, int) or isinstance(val, bool) or not 0 < val <= 730):
                    err(f"{key}.{k} must be null or a whole number from 1 to 730")
            if days is not None and months is not None:
                err(f"{key}: only one of min_days and min_months")
            if days is None and months is None and read_ok is not False and not any("before sailing" in w for w in warnings):
                err(f"{key}: no time before sailing needs the matching warning")
        elif listed is False:
            for k in ("title", "text", "types", "min_days", "min_months") + (("name", "credits") if v == 2 else ()):
                if du.get(k) is not None:
                    err(f"{key}.{k} must be null when no banner is listed")
        read_on, since = date(du.get("read_on")), date(du.get("since"))
        if not read_on or not since:
            err(f"{key}.read_on and {key}.since must be dates like 2026-10-29")
        elif since > read_on:
            err(f"{key}.since is after {key}.read_on")
        if read_on and checked_on:
            if read_ok and read_on != checked_on:
                err(f"{key}.read_on must be checked_on when the page was read")
            if read_on > checked_on:
                err(f"{key}.read_on is after checked_on")

    ch = data.get("last_change")
    if ch is None:
        if du is not None:
            err("last_change is missing although a state was read")
    elif not isinstance(ch, dict):
        err("last_change must be an object or null")
    else:
        extra, missing = set(ch) - CHANGE_KEYS[v], CHANGE_KEYS[v] - set(ch)
        if extra:
            err(f"last_change: unexpected keys {sorted(extra)}")
        if missing:
            err(f"last_change: missing keys {sorted(missing)}")
        kind = ch.get("kind")
        if kind not in ("started", "appeared", "ended", "changed"):
            err("last_change.kind must be started, appeared, ended or changed")
        if not date(ch.get("on")):
            err("last_change.on must be a date like 2026-10-29")
        if not isinstance(ch.get("marker"), str) or not re.fullmatch(MARKER[v], ch["marker"]):
            err("last_change.marker must look like offer-0123456789ab")
        if not isinstance(ch.get("reported"), bool):
            err("last_change.reported must be true or false")
        for side in ("old", "new"):
            listed, text = ch.get(f"{side}_listed"), ch.get(f"{side}_text")
            name, credits = ch.get(f"{side}_name"), ch.get(f"{side}_credits")
            if side == "old" and kind == "started":
                if listed is not None or text is not None or name is not None or credits is not None:
                    err("last_change: a started change has no old state")
                continue
            if not isinstance(listed, bool):
                err(f"last_change.{side}_listed must be true or false")
            elif listed and not short_text(text):
                err(f"last_change.{side}_text must be the banner text")
            elif not listed and text is not None:
                err(f"last_change.{side}_text must be null when no banner was listed")
            if v == 2 and isinstance(listed, bool):
                if listed and not name_ok(name):
                    err(f"last_change.{side}_name must be the offer's name")
                if listed and credits is not None and not credits_ok(credits):
                    err(f"last_change.{side}_credits must be null or a whole number from 2 to 4")
                if not listed and (name is not None or credits is not None):
                    err(f"last_change.{side}_name and {side}_credits must be null when no banner was listed")
        old = tuple(ch.get(f"old_{k}") for k in ("listed", "name", "credits", "text"))
        new = tuple(ch.get(f"new_{k}") for k in ("listed", "name", "credits", "text"))
        if kind == "appeared" and not (ch.get("old_listed") is False and ch.get("new_listed") is True):
            err("last_change: appeared means old_listed false and new_listed true")
        if kind == "ended" and not (ch.get("old_listed") is True and ch.get("new_listed") is False):
            err("last_change: ended means old_listed true and new_listed false")
        if kind == "changed" and not (ch.get("old_listed") and ch.get("new_listed") and old != new):
            err("last_change: changed means both listed with a different name, number of credits or text")
        if isinstance(du, dict):
            saved = (du.get("listed"), du.get("text")) if v == 1 else (du.get("listed"), du.get("name"), du.get("credits"), du.get("text"))
            last = (ch.get("new_listed"), ch.get("new_text")) if v == 1 else new
            if saved != last:
                err(f"last_change's new state must be the saved {key} state")
    return errors


def main():
    args = sys.argv[1:]
    any_schema = "--any-schema" in args
    args = [a for a in args if a != "--any-schema"]
    if len(args) != 1:
        print("usage: check_offers.py [--any-schema] PATH", file=sys.stderr)
        return 2
    path = args[0]
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"FAIL {path}: cannot read JSON ({e})")
        return 1
    errors = check(data, any_schema=any_schema)
    if errors:
        print(f"FAIL {path}: {len(errors)} problem(s)")
        for e in errors:
            print("  - " + e)
        return 1
    du = data[OFFER_KEY[data["schema_version"]]]
    if du is None:
        state = "not read yet"
    elif not du["listed"]:
        state = "no multi-credit offer"
    else:
        state = f"{du.get('name') or du['title']} listed ({du.get('credits') or 'unknown'} credits)"
    print(f"OK {path}: {state}, checked {data['checked_on']}, read_ok {data['read_ok']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
