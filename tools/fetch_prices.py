#!/usr/bin/env python3
"""Fetch cabin prices for the two June 2027 sailings from NCL's public sailing pages.

Writes a new data file. It never touches the old one: the workflow runs the format
check on the new file and only then replaces data/prices.json.

  python3 tools/fetch_prices.py --out data/prices.new.json --previous data/prices.json
  python3 tools/fetch_prices.py --out data/prices.new.json --previous data/prices.json --cruisefeed

NCL: one page load per sailing per guest count (2, 3, 4, 5), so 8 page loads. Free.
CruiseFeed (only with --cruisefeed): /v1/stats and /v1/ship-names first (both free), then
one /v1/cruises lookup per sailing (1 result each). Skipped when the CRUISEFEED_KEY
environment variable is missing or empty, or when fewer than 150 results remain.
The key is only ever sent in the Authorization header. It is never printed or saved.
"""
import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

SCHEMA_VERSION = 1
GUEST_COUNTS = [2, 3, 4, 5]
CRUISE_LINE = "Norwegian Cruise Line"
CRUISEFEED_BASE = "https://api.cruisefeed.io/v1"
CRUISEFEED_MIN_REMAINING = 150
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"

# The sailings the family is choosing between. Owner-provided tax estimates are shown
# only as a note: NCL's prices already include taxes, fees and port expenses.
SAILINGS = [
    {
        "id": "getaway-2027-06-11",
        "ship": "Norwegian Getaway",
        "ship_short": "Getaway",
        "itinerary_code": "GETAWAY3MIANPINASMIA",
        "depart": "2027-06-11",
        "taxes_per_guest_estimate": 200,
    },
    {
        "id": "aura-2027-06-14",
        "ship": "Norwegian Aura",
        "ship_short": "Aura",
        "itinerary_code": "AURA5MIAPOPNPIMIA",
        "depart": "2027-06-14",
        "taxes_per_guest_estimate": 210,
    },
]
TAX_ESTIMATE_SOURCE = {"source": "owner estimate", "date": "2026-10-06"}

# NCL's broad cabin type codes and how the page matches them like for like.
MATCH_KEYS = {
    "STUDIO": "studio",
    "INSIDE": "inside",
    "OCEANVIEW": "oceanview",
    "BALCONY": "balcony",
    "MINISUITE": "mini_suite",
    "SUITE": "suite",
    "HAVEN": "haven",
}
TERMINAL = {"confirmed": False, "text": "Expected: Terminal B (confirm on your eDocs)"}


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def http_get(url, headers, timeout=90, tries=3):
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as res:
                return res.status, dict(res.headers), res.read()
        except urllib.error.HTTPError as e:
            # A clear refusal is not worth retrying.
            if e.code in (401, 403, 404):
                return e.code, dict(e.headers or {}), e.read()
            last = e
        except Exception as e:  # network errors, timeouts
            last = e
        time.sleep(2 ** (attempt + 1))
    raise RuntimeError(f"GET failed after {tries} tries: {url.split('?')[0]} ({last})")


def utc_date(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%d")


def utc_hhmm(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%H:%M")


def fetch_ncl_page(code, guests):
    url = f"https://www.ncl.com/cruises/{code}?numberOfGuests={guests}"
    status, _, body = http_get(url, {"User-Agent": USER_AGENT, "Accept": "*/*"})
    if status != 200:
        raise RuntimeError(f"NCL answered HTTP {status} for {code} at {guests} guests")
    raw = body.decode("utf-8", errors="replace")
    m = re.search(r'data-pricing-sailings="([^"]*)"', raw)
    if not m:
        raise RuntimeError(
            f"No pricing data on the NCL page for {code} at {guests} guests "
            "(blocked, redirected to a stripped page, or the page layout changed)")
    return url, json.loads(html.unescape(m.group(1)))


def ports_from_events(events, depart, nights):
    # NCL stores port times as local clock time written in UTC, so read them back in UTC.
    start = dt.date.fromisoformat(depart)
    days = []
    for i in range(nights + 1):
        day = (start + dt.timedelta(days=i)).isoformat()
        evs = [e for e in events if utc_date(e["date"]) == day]
        arrive = next((e for e in evs if e.get("event") == "A" and e.get("portCode")), None)
        leave = next((e for e in evs if e.get("event") == "D" and e.get("portCode")), None)
        port = (arrive or leave or {}).get("portName")
        if not port:
            days.append({"date": day, "sea": True})
            continue
        days.append({
            "date": day,
            "port": port,
            "arrive": utc_hhmm(arrive["date"]) if arrive and i > 0 else None,
            "depart": utc_hhmm(leave["date"]) if leave and i < nights else None,
        })
    return days


def fetch_sailing(cfg):
    categories = {}
    sailing_meta = None
    url2 = None
    for g in GUEST_COUNTS:
        url, data = fetch_ncl_page(cfg["itinerary_code"], g)
        match = [s for s in data if utc_date(s["departureDate"]) == cfg["depart"]]
        if not match:
            raise RuntimeError(f"NCL no longer lists the {cfg['ship']} sailing on {cfg['depart']}")
        s = match[0]
        rooms = s.get("staterooms") or []
        # Make sure NCL priced the page for the guest count we asked for.
        links = [r.get("linkToBookingParams", "") for r in rooms]
        if not any(f"guestCount={g}" in l for l in links):
            raise RuntimeError(f"NCL did not price {cfg['ship']} for {g} guests")
        if g == 2:
            sailing_meta, url2 = s, url
        for r in rooms:
            code = r["code"]
            cat = categories.setdefault(code, {
                "code": code,
                "title": r.get("title") or code.title(),
                "match": MATCH_KEYS.get(code, code.lower()),
                "by_guests": {},
            })
            price = r.get("price")
            available = r.get("status") == "AVAILABLE" and isinstance(price, (int, float)) and price > 0
            entry = {"status": r.get("status") or "UNKNOWN", "available": available}
            if available:
                entry["price_pp"] = int(round(price))
                entry["base_pp"] = int(round(r["basePrice"])) if isinstance(r.get("basePrice"), (int, float)) else None
                entry["cabin_total"] = entry["price_pp"] * g
            cat["by_guests"][str(g)] = entry
        log(f"  {cfg['ship']} {g} guests: {len(rooms)} cabin types")
    # Estimated add-on: what the cheapest cabin for N guests costs on top of the cheapest for 2.
    for cat in categories.values():
        two = cat["by_guests"].get("2", {})
        for g in GUEST_COUNTS[1:]:
            e = cat["by_guests"].setdefault(str(g), {"status": "MISSING", "available": False})
            if e.get("available") and two.get("available"):
                e["addon_vs_2"] = e["cabin_total"] - two["cabin_total"]
    nights = round((sailing_meta["returnDate"] - sailing_meta["departureDate"]) / 86400000)
    return {
        "id": cfg["id"],
        "ship": cfg["ship"],
        "ship_short": cfg["ship_short"],
        "itinerary_code": cfg["itinerary_code"],
        "package_id": sailing_meta["packageId"],
        "depart": cfg["depart"],
        "return": utc_date(sailing_meta["returnDate"]),
        "nights": nights,
        "url": url2.split("?")[0],
        "source": "NCL website",
        "saved_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d"),
        "prices_include_taxes": True,
        "taxes_per_guest_estimate": dict(TAX_ESTIMATE_SOURCE, amount=cfg["taxes_per_guest_estimate"]),
        "free_at_sea_per_guest": None,
        "terminal": TERMINAL,
        "ports": ports_from_events(sailing_meta.get("events") or [], cfg["depart"], nights),
        "categories": list(categories.values()),
    }


def find_remaining(obj):
    """CruiseFeed's /v1/stats shape is not documented here, so look for a 'remaining' number."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if "remaining" in k.lower() and isinstance(v, (int, float)) and not isinstance(v, bool):
                return int(v)
        for v in obj.values():
            r = find_remaining(v)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = find_remaining(v)
            if r is not None:
                return r
    return None


def cruisefeed_check(sailings, previous):
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    block = {"checked_at": now, "remaining": None, "status": "skipped", "warning": None, "sailings": {}}
    key = os.environ.get("CRUISEFEED_KEY", "").strip()
    if not key:
        block["warning"] = "CRUISEFEED_KEY repo secret is not set. CruiseFeed cross check skipped."
        return block
    headers = {"Authorization": "Bearer " + key, "Accept": "application/json", "User-Agent": "cruise-cabin-comparison"}
    try:
        status, _, body = http_get(CRUISEFEED_BASE + "/stats", headers, timeout=30)
        if status != 200:
            block["warning"] = f"CruiseFeed /v1/stats answered HTTP {status}. Cross check skipped."
            return block
        remaining = find_remaining(json.loads(body))
        block["remaining"] = remaining
        if remaining is None:
            block["warning"] = "Could not read the remaining allowance from /v1/stats. Cross check skipped to protect the allowance."
            return block
        if remaining < CRUISEFEED_MIN_REMAINING:
            block["warning"] = f"Only {remaining} CruiseFeed results remain (below {CRUISEFEED_MIN_REMAINING}). Cross check skipped."
            return block
        status, _, body = http_get(CRUISEFEED_BASE + "/ship-names", headers, timeout=30)
        names = json.loads(body) if status == 200 else []
        flat = json.dumps(names)
        for s in sailings:
            if f'"{s["ship"]}"' not in flat:
                block["sailings"][s["id"]] = {"error": f"{s['ship']} not found in /v1/ship-names"}
                continue
            q = urllib.parse.urlencode({
                "cruise_line": CRUISE_LINE, "ship_name": s["ship"],
                "departure_from": s["depart"], "departure_to": s["depart"], "limit": 1,
            })
            status, hdrs, body = http_get(f"{CRUISEFEED_BASE}/cruises?{q}", headers, timeout=30)
            lower = {k.lower(): v for k, v in hdrs.items()}
            if lower.get("x-results-remaining", "").isdigit():
                block["remaining"] = int(lower["x-results-remaining"])
            if status != 200:
                block["sailings"][s["id"]] = {"error": f"HTTP {status}"}
                continue
            data = json.loads(body)
            items = data if isinstance(data, list) else (data.get("data") or data.get("cruises") or data.get("results") or [])
            hit = next((c for c in items if isinstance(c, dict) and c.get("departure_date") == s["depart"]), None)
            if not hit:
                block["sailings"][s["id"]] = {"error": "sailing not found"}
                continue
            ncl_two = [c["by_guests"]["2"]["price_pp"] for c in s["categories"]
                       if c["by_guests"].get("2", {}).get("available") and c["code"] != "STUDIO"]
            block["sailings"][s["id"]] = {
                "price_amount": hit.get("price_amount"),
                "price_currency": hit.get("price_currency"),
                "sold_out": hit.get("sold_out"),
                "scraped_at": hit.get("scraped_at"),
                "ncl_lowest_pp_2_guests": min(ncl_two) if ncl_two else None,
            }
        block["status"] = "checked"
    except Exception as e:  # never let the cross check break the daily NCL refresh
        block["warning"] = f"CruiseFeed cross check failed: {type(e).__name__}. Skipped."
        block["status"] = "skipped"
    return block


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--previous", help="the current data file, to carry the last CruiseFeed result forward")
    ap.add_argument("--cruisefeed", action="store_true", help="run the weekly CruiseFeed cross check")
    args = ap.parse_args()

    previous = {}
    if args.previous and os.path.exists(args.previous):
        try:
            with open(args.previous, encoding="utf-8") as f:
                previous = json.load(f)
        except Exception:
            previous = {}

    sailings = []
    for cfg in SAILINGS:
        log(f"Fetching {cfg['ship']} {cfg['depart']} from NCL")
        sailings.append(fetch_sailing(cfg))

    if args.cruisefeed:
        log("Running the CruiseFeed cross check")
        cruisefeed = cruisefeed_check(sailings, previous)
    else:
        cruisefeed = previous.get("cruisefeed") or {
            "checked_at": None, "remaining": None, "status": "never_run",
            "warning": "Not checked yet. It runs weekly once the CRUISEFEED_KEY repo secret is added.", "sailings": {},
        }
    if cruisefeed.get("warning"):
        log("CruiseFeed: " + cruisefeed["warning"])

    out = {
        "schema_version": SCHEMA_VERSION,
        "saved_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "NCL website sailing pages, one page per guest count (2 to 5)",
        "guest_counts": GUEST_COUNTS,
        "cruisefeed": cruisefeed,
        "sailings": sailings,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
        f.write("\n")
    log(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
