#!/usr/bin/env python3
"""Format check for the price data file the page reads (data/prices.json).

  python3 tools/check_prices.py data/prices.new.json

Exits 1 and lists every problem when the file is malformed or a sailing is missing.
The refresh workflow runs this on the new file before it replaces the old one.
"""
import datetime as dt
import json
import sys

EXPECTED_SAILINGS = {"getaway-2027-06-11", "aura-2027-06-14"}
GUEST_KEYS = ["2", "3", "4", "5"]
STATUSES = {"AVAILABLE", "SOLD_OUT", "NOT_AVAILABLE", "MISSING", "UNKNOWN"}
MATCH_KEYS = {"studio", "inside", "oceanview", "balcony", "mini_suite", "suite", "haven"}
CRUISEFEED_STATUSES = {"checked", "skipped", "never_run"}


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def check(data):
    errors = []
    err = errors.append

    if not isinstance(data, dict):
        return ["the file is not a JSON object"]
    if data.get("schema_version") != 1:
        err("schema_version must be 1")
    try:
        dt.datetime.strptime(data.get("saved_at", ""), "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        err("saved_at must look like 2026-10-07T11:17:00Z")
    if data.get("guest_counts") != [2, 3, 4, 5]:
        err("guest_counts must be [2, 3, 4, 5]")

    cf = data.get("cruisefeed")
    if not isinstance(cf, dict):
        err("cruisefeed block is missing")
    else:
        for k in ("checked_at", "remaining", "status", "warning", "sailings"):
            if k not in cf:
                err(f"cruisefeed.{k} is missing")
        if cf.get("status") not in CRUISEFEED_STATUSES:
            err(f"cruisefeed.status must be one of {sorted(CRUISEFEED_STATUSES)}")
        if cf.get("remaining") is not None and not is_int(cf.get("remaining")):
            err("cruisefeed.remaining must be a whole number or null")

    sailings = data.get("sailings")
    if not isinstance(sailings, list):
        return errors + ["sailings must be a list"]
    ids = [s.get("id") for s in sailings if isinstance(s, dict)]
    for missing in sorted(EXPECTED_SAILINGS - set(ids)):
        err(f"sailing {missing} is missing")
    if len(ids) != len(set(ids)):
        err("a sailing appears twice")

    for s in sailings:
        sid = s.get("id", "?")
        p = f"sailing {sid}"
        for k in ("ship", "ship_short", "itinerary_code", "url", "source", "saved_at"):
            if not isinstance(s.get(k), str) or not s.get(k):
                err(f"{p}: {k} is missing")
        for k in ("depart", "return", "saved_at"):
            try:
                dt.date.fromisoformat(s.get(k, ""))
            except (TypeError, ValueError):
                err(f"{p}: {k} must be a YYYY-MM-DD date")
        if not is_int(s.get("nights")) or s.get("nights", 0) < 1:
            err(f"{p}: nights must be a positive whole number")
        if s.get("prices_include_taxes") is not True:
            err(f"{p}: prices_include_taxes must be true")
        tax = s.get("taxes_per_guest_estimate")
        if not isinstance(tax, dict) or not is_int(tax.get("amount")) or not tax.get("source") or not tax.get("date"):
            err(f"{p}: taxes_per_guest_estimate needs amount, source and date")
        fas = s.get("free_at_sea_per_guest")
        if fas is not None and not (isinstance(fas, (int, float)) and fas >= 0):
            err(f"{p}: free_at_sea_per_guest must be a number or null")
        term = s.get("terminal")
        if not isinstance(term, dict) or not isinstance(term.get("text"), str):
            err(f"{p}: terminal.text is missing")
        ports = s.get("ports")
        if not isinstance(ports, list) or len(ports) != (s.get("nights") or 0) + 1:
            err(f"{p}: ports must have one entry per day (nights + 1)")

        cats = s.get("categories")
        if not isinstance(cats, list) or not cats:
            err(f"{p}: categories is empty")
            continue
        any_available_for_2 = False
        for c in cats:
            cp = f"{p} category {c.get('code', '?')}"
            if not c.get("code") or not c.get("title"):
                err(f"{cp}: code and title are required")
            if c.get("match") not in MATCH_KEYS:
                err(f"{cp}: match must be one of {sorted(MATCH_KEYS)}")
            bg = c.get("by_guests")
            if not isinstance(bg, dict) or sorted(bg) != GUEST_KEYS:
                err(f"{cp}: by_guests must have exactly the keys 2, 3, 4, 5")
                continue
            for g in GUEST_KEYS:
                e = bg[g]
                ep = f"{cp} at {g} guests"
                if e.get("status") not in STATUSES:
                    err(f"{ep}: unknown status {e.get('status')!r}")
                if not isinstance(e.get("available"), bool):
                    err(f"{ep}: available must be true or false")
                    continue
                if e["available"]:
                    if e.get("status") != "AVAILABLE":
                        err(f"{ep}: available but status is {e.get('status')}")
                    if not is_int(e.get("price_pp")) or e["price_pp"] <= 0:
                        err(f"{ep}: price_pp must be a positive whole number")
                    elif e.get("cabin_total") != e["price_pp"] * int(g):
                        err(f"{ep}: cabin_total must equal price_pp x {g}")
                    if g != "2" and bg["2"].get("available") and not is_int(e.get("addon_vs_2")):
                        err(f"{ep}: addon_vs_2 is missing")
                    if g == "2" and c.get("code") != "STUDIO":
                        any_available_for_2 = True
                elif "price_pp" in e:
                    err(f"{ep}: not available but has a price")
        if not any_available_for_2:
            err(f"{p}: no cabin type is available for 2 guests (NCL may have stopped selling it)")
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
