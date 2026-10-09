#!/usr/bin/env python3
"""Format check for the price data file the page reads (data/prices.json).

  python3 tools/check_prices.py data/prices.new.json

Exits 1 and lists every problem when the file is malformed, a sailing is missing,
or a formula cross check failed. The refresh workflow runs this on the new file
before it replaces the old one.
"""
import datetime as dt
import json
import sys

EXPECTED_SAILINGS = {"getaway-2027-06-11", "aura-2027-06-14"}
GUEST_KEYS = ["2", "3", "4", "5"]
MATCH_KEYS = {"studio", "inside", "oceanview", "balcony", "mini_suite", "suite", "haven"}


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_date(v):
    try:
        dt.date.fromisoformat(v)
        return True
    except (TypeError, ValueError):
        return False


def check(data):
    errors = []
    err = errors.append

    if not isinstance(data, dict):
        return ["the file is not a JSON object"]
    if data.get("schema_version") != 2:
        err("schema_version must be 2")
    try:
        dt.datetime.strptime(data.get("saved_at", ""), "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        err("saved_at must look like 2026-10-07T10:17:00Z")
    if data.get("guest_counts") != [2, 3, 4, 5]:
        err("guest_counts must be [2, 3, 4, 5]")

    checks = data.get("checks")
    if not isinstance(checks, dict) or not isinstance(checks.get("formula"), list) \
            or not isinstance(checks.get("extra_guest_mismatches"), list):
        err("checks.formula and checks.extra_guest_mismatches must be lists")
    else:
        if len(checks["formula"]) != len(EXPECTED_SAILINGS) * len(GUEST_KEYS):
            err("checks.formula must have one entry per sailing per party size")
        for c in checks["formula"]:
            if c.get("ok") is not True:
                err(f"formula cross check failed: {c}")
        ages = checks.get("ages")
        if not isinstance(ages, list) or len(ages) != len(EXPECTED_SAILINGS):
            err("checks.ages must have one entry per sailing")
        else:
            for c in ages:
                if c.get("ok") is not True:
                    err(f"age cross check failed: {c}")

    rates = data.get("rates")
    if not isinstance(rates, dict):
        err("rates block is missing")
    else:
        need = {"free_at_sea_plus": ["adult_per_day", "child_per_day"],
                "open_bar": ["per_day_2_to_5_nights", "per_day_6_plus_nights", "soda_per_day"],
                "service_charge": ["suite_haven_per_night", "standard_per_night"]}
        for key, fields in need.items():
            r = rates.get(key)
            if not isinstance(r, dict):
                err(f"rates.{key} is missing")
                continue
            for f in fields:
                if not isinstance(r.get(f), (int, float)) or isinstance(r.get(f), bool) or r[f] <= 0:
                    err(f"rates.{key}.{f} must be a positive number")
            if not str(r.get("source", "")).startswith("https://www.ncl.com/"):
                err(f"rates.{key}.source must be an NCL page")
            try:
                dt.date.fromisoformat(r.get("checked_at", ""))
            except (TypeError, ValueError):
                err(f"rates.{key}.checked_at must be a date")
        sc = rates.get("service_charge") or {}
        if not is_int(sc.get("min_age")) or not isinstance(sc.get("suite_haven_types"), list):
            err("rates.service_charge needs min_age and suite_haven_types")

    sailings = data.get("sailings")
    if not isinstance(sailings, list):
        return errors + ["sailings must be a list"]
    ids = [s.get("id") for s in sailings if isinstance(s, dict)]
    for missing in sorted(EXPECTED_SAILINGS - set(ids)):
        err(f"sailing {missing} is missing")
    if len(ids) != len(set(ids)):
        err("a sailing appears twice")

    for s in sailings:
        p = f"sailing {s.get('id', '?')}"
        for k in ("ship", "ship_short", "itinerary_code", "package_id", "url", "source"):
            if not isinstance(s.get(k), str) or not s.get(k):
                err(f"{p}: {k} is missing")
        for k in ("depart", "return", "saved_at"):
            if not is_date(s.get(k)):
                err(f"{p}: {k} must be a YYYY-MM-DD date")
        if not is_int(s.get("nights")) or s.get("nights", 0) < 1:
            err(f"{p}: nights must be a positive whole number")
        if not is_int(s.get("taxes_per_guest")) or s["taxes_per_guest"] <= 0:
            err(f"{p}: taxes_per_guest must be a positive whole number")
        grat = s.get("gratuities")
        for k in ("open_bar", "specialty_dining"):
            g = grat.get(k) if isinstance(grat, dict) else None
            if not isinstance(g, dict) or not g.get("title") or not isinstance(g.get("per_guest"), (int, float)) or g["per_guest"] < 0:
                err(f"{p}: gratuities.{k} needs a title and a per_guest amount")
        soda = (grat.get("open_bar") or {}).get("soda_under_21_position_2") if isinstance(grat, dict) else None
        if not isinstance(soda, (int, float)) or soda < 0:
            err(f"{p}: gratuities.open_bar.soda_under_21_position_2 must be a number")
        if not isinstance((s.get("terminal") or {}).get("text"), str):
            err(f"{p}: terminal.text is missing")
        ports = s.get("ports")
        if not isinstance(ports, list) or len(ports) != (s.get("nights") or 0) + 1:
            err(f"{p}: ports must have one entry per day (nights + 1)")
        elif any(not is_date(d.get("date")) for d in ports):
            err(f"{p}: every port day needs a date")

        types = s.get("types")
        if not isinstance(types, list) or not types:
            err(f"{p}: types is empty")
            continue
        available_for = {g: False for g in GUEST_KEYS}
        for t in types:
            tp = f"{p} type {t.get('code', '?')}"
            if not t.get("code") or not t.get("title"):
                err(f"{tp}: code and title are required")
            if t.get("match") not in MATCH_KEYS:
                err(f"{tp}: match must be one of {sorted(MATCH_KEYS)}")
            cats = t.get("categories")
            if not isinstance(cats, list):
                err(f"{tp}: categories must be a list")
                continue
            for c in cats:
                cp = f"{tp} category {c.get('code', '?')}"
                if not c.get("code") or not c.get("title"):
                    err(f"{cp}: code and title are required")
                for k in ("guarantee", "solo"):
                    if not isinstance(c.get(k), bool):
                        err(f"{cp}: {k} must be true or false")
                if c.get("capacity") is not None and (not is_int(c["capacity"]) or c["capacity"] < 1):
                    err(f"{cp}: capacity must be a positive whole number or null")
                if not isinstance(c.get("description"), str) or not c["description"].startswith(c.get("title") or "\0"):
                    err(f"{cp}: description must start with the category title")
                decks = c.get("decks")
                if decks is not None and (not isinstance(decks, list) or not decks or not all(is_int(d) for d in decks)):
                    err(f"{cp}: decks must be a list of deck numbers or null")
                locs = c.get("location")
                if locs is not None and (not isinstance(locs, list) or not set(locs) <= {"forward", "midship", "aft"}):
                    err(f"{cp}: location must be a list of forward, midship, aft or null")
                if (decks or locs) and not c.get("details_source"):
                    err(f"{cp}: decks or location without a details_source")
                if c.get("guarantee") and (decks or locs):
                    err(f"{cp}: guarantee cabins must not list decks or a location")
                if c.get("size") is not None and not isinstance(c["size"], str):
                    err(f"{cp}: size must be text or null")
                if not isinstance(c.get("shares_ncl_description_with"), list):
                    err(f"{cp}: shares_ncl_description_with must be a list")
                bg = c.get("by_guests")
                if not isinstance(bg, dict) or sorted(bg) != GUEST_KEYS:
                    err(f"{cp}: by_guests must have exactly the keys 2, 3, 4, 5")
                    continue
                for g in GUEST_KEYS:
                    e = bg[g]
                    ep = f"{cp} at {g} guests"
                    if not isinstance(e.get("available"), bool) or not isinstance(e.get("sold_out"), bool):
                        err(f"{ep}: available and sold_out must be true or false")
                        continue
                    if e["available"]:
                        pp = e.get("price_pp")
                        if not isinstance(pp, (int, float)) or isinstance(pp, bool) or pp <= 0:
                            err(f"{ep}: price_pp must be a positive number")
                        elif not is_int(e.get("cabin_total")) or abs(e["cabin_total"] - pp * int(g)) > 0.5 + 0.01 * int(g):
                            err(f"{ep}: cabin_total must be price_pp x {g}, rounded to whole dollars")
                        if g != "2" and bg["2"].get("available") and not is_int(e.get("added_vs_2")):
                            err(f"{ep}: added_vs_2 is missing")
                        if not c.get("solo"):
                            available_for[g] = True
                        if "cabins_left" in e or "count_reliable" in e:
                            err(f"{ep}: cabin counts belong in data/counts.json, not in prices")
                    else:
                        if "price_pp" in e:
                            err(f"{ep}: not available but has a price")
                        if not isinstance(e.get("reason"), str) or not e["reason"]:
                            err(f"{ep}: unavailable without a reason")
        for g, ok in available_for.items():
            if not ok:
                err(f"{p}: no cabin is available for {g} guests")
    return errors


def main():
    if len(sys.argv) != 2:
        print("usage: check_prices.py PATH", file=sys.stderr)
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
    print(f"OK {path}: {len(data['sailings'])} sailings, saved_at {data['saved_at']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
