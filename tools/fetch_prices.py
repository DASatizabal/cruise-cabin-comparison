#!/usr/bin/env python3
"""Fetch cabin prices for the two June 2027 sailings from NCL's vacation-builder API.

Writes a new data file. It never touches the old one: the workflow runs the format
check on the new file and only then replaces data/prices.json.

  python3 tools/fetch_prices.py --out data/prices.new.json

Calls per run (2 seconds apart, no cookies, nothing is held or booked):
  - route-events: 1 per ship, for the day by day itinerary and to confirm the departure date (2)
  - stateroom-types-availability: 1 per ship per party size 2, 3, 4, 5 (8)
  - price-summary: 1 per ship per party size, for the cheapest available category,
    to read NCL's tax line and Free at Sea gratuity lines (8)

Cross checks are logged in the data file under "checks":
  - extra_guest: per category, (total at N minus total at 2) / (N minus 2) should match
    across 3, 4 and 5 guests within $5. A mismatch is logged, never fatal.
  - formula: average per person price x guests + gratuities x guests should match the
    price summary total within $5. A mismatch fails the run (exit 1).
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.request

SCHEMA_VERSION = 2
GUEST_COUNTS = [2, 3, 4, 5]
PAUSE_SECONDS = 2
TOLERANCE = 5
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
API = "https://www.ncl.com/api"
AVAILABILITY_URL = API + "/vacation-builder/v2/stateroom-types-availability"
PRICE_SUMMARY_URL = API + "/vacation-builder/price-summary"
ROUTE_EVENTS_URL = API + "/cruises/v1/route-events/{package_id}"

SAILINGS = [
    {"id": "getaway-2027-06-11", "ship": "Norwegian Getaway", "ship_short": "Getaway",
     "itinerary_code": "GETAWAY3MIANPINASMIA", "package_id": "24223992", "depart": "2027-06-11"},
    {"id": "aura-2027-06-14", "ship": "Norwegian Aura", "ship_short": "Aura",
     "itinerary_code": "AURA5MIAPOPNPIMIA", "package_id": "25729291", "depart": "2027-06-14"},
]

MATCH_KEYS = {
    "STUDIO": "studio", "INSIDE": "inside", "OCEANVIEW": "oceanview", "BALCONY": "balcony",
    "MINISUITE": "mini_suite", "SUITE": "suite", "HAVEN": "haven",
}
SOLO_CODES = {"T1", "IT", "OT", "BT"}          # one-guest cabins, hidden on the page
GUARANTEE_CODES = {"IX", "OX", "BX", "MX"}     # NCL picks the cabin location
TERMINAL = {"confirmed": False, "text": "Expected: Terminal B (confirm on your eDocs)"}

# Never touch anything that holds a cabin. NCL's cabin/manage-cabin call carries
# recommendAndHold and puts a temporary hold on a real cabin.
FORBIDDEN = re.compile(r"manage-cabin|hold", re.I)

_last_call = 0.0


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def request(url, body=None, tries=3):
    """GET (body None) or POST JSON. Refuses forbidden addresses. Pauses between calls."""
    global _last_call
    if FORBIDDEN.search(url):
        raise RuntimeError(f"Refusing to call {url}: it could hold a cabin")
    last = None
    for attempt in range(tries):
        wait = PAUSE_SECONDS - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
            with urllib.request.urlopen(req, timeout=60) as res:
                return json.loads(res.read())
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 404):
                raise RuntimeError(f"NCL answered HTTP {e.code} for {url} (blocked or moved)")
            last = e
        except Exception as e:
            last = e
        time.sleep(2 ** (attempt + 1))
    raise RuntimeError(f"Request failed after {tries} tries: {url} ({last})")


def utc(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc)


def hhmm(text):
    """'4:00 PM' -> '16:00'."""
    if not text:
        return None
    t = dt.datetime.strptime(text.strip().upper(), "%I:%M %p")
    return t.strftime("%H:%M")


def fetch_ports(cfg):
    events = request(ROUTE_EVENTS_URL.format(package_id=cfg["package_id"]))
    if not events:
        raise RuntimeError(f"No itinerary for {cfg['ship']} packageId {cfg['package_id']}")
    # NCL stores times as local clock time written in UTC, so the UTC date is the local date.
    first = utc(events[0]["date"]).strftime("%Y-%m-%d")
    if first != cfg["depart"]:
        raise RuntimeError(f"packageId {cfg['package_id']} departs {first}, expected {cfg['depart']}")
    ports = []
    for e in events:
        day = utc(e["date"]).strftime("%Y-%m-%d")
        if e.get("eventType") == "sea":
            ports.append({"date": day, "sea": True})
        else:
            ports.append({"date": day, "port": e.get("title"), "arrive": hhmm(e.get("arrivalTime")),
                          "depart": hhmm(e.get("departureTime"))})
    return ports


def fetch_availability(cfg, guests):
    body = {"sailingFilters": [{"packageId": cfg["package_id"], "numberOfGuests": guests, "filterId": "0"}]}
    res = request(AVAILABILITY_URL, body)
    try:
        return res["results"][0]["result"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(f"Unexpected availability answer for {cfg['ship']} at {guests} guests")


def default_fare_codes(result):
    """Free at Sea promotion code for each broad cabin type (e.g. ALL4CHO, CHOALL4M)."""
    codes = {}
    for group in result.get("offerGroups", []):
        if group.get("code") != "FREE-AT-SEA":
            continue
        for p in group.get("promotionsInGroup", []):
            if not p.get("isDefaultInGroup"):
                continue
            promo = p.get("promotion", {})
            for t in promo.get("stateroomTypes", []):
                if promo.get("promotionCodes"):
                    codes.setdefault(t, promo["promotionCodes"][0])
    return codes


def fetch_price_summary(cfg, guests, type_code, cat_code, fare_code):
    body = {
        "packageId": cfg["package_id"],
        "stateroomFilters": [{"id": "0", "mainCabin": True, "numberOfGuests": guests,
                              "stateroomTypeCode": type_code, "pricedCategoryCode": cat_code,
                              "fareCodes": [fare_code], "guests": [], "vouchers": []}],
        "userFareCodes": [],
    }
    res = request(PRICE_SUMMARY_URL, body)
    if "total" not in res:
        raise RuntimeError(f"Unexpected price summary for {cfg['ship']} {cat_code} at {guests} guests")
    lines = {}
    for group in res["staterooms"][0]["pricing"]["priceGroups"]:
        for item in group.get("priceItems", []):
            if item.get("itemType") == "strikethrough" or not item.get("guests"):
                continue
            lines[item["code"]] = {"group": group["code"], "title": item.get("title"),
                                   "per_guest": [g.get("price") for g in item["guests"]]}
    fare = sum(sum(l["per_guest"]) for l in lines.values() if l["group"] == "STATEROOM")
    taxes = lines.get("taxes-and-fees", {}).get("per_guest") or []
    bar = next((l for c, l in lines.items() if c.startswith("unlimited-open-bar")), None)
    dining = next((l for c, l in lines.items() if c.startswith("specialty-dining")), None)
    return {
        "guests": guests,
        "category": cat_code,
        "fare_code": fare_code,
        "fare_total": fare,
        "fare_per_guest": [l for l in next((l["per_guest"] for l in lines.values() if l["group"] == "STATEROOM"), [])],
        "taxes_per_guest": taxes,
        "open_bar": {"title": bar["title"], "per_guest": bar["per_guest"]} if bar else None,
        "specialty_dining": {"title": dining["title"], "per_guest": dining["per_guest"]} if dining else None,
        "grand_total": res["total"]["grandTotal"],
    }


def fetch_sailing(cfg, checks):
    log(f"{cfg['ship']} {cfg['depart']} (packageId {cfg['package_id']})")
    ports = fetch_ports(cfg)
    nights = len(ports) - 1
    types = {}
    capacity = {}
    fare_codes = {}
    summaries = []
    for g in GUEST_COUNTS:
        result = fetch_availability(cfg, g)
        if g == 2:
            fare_codes = default_fare_codes(result)
        cheapest = None
        for t in result.get("stateroomTypesPricing", []):
            tcode = t["code"]
            tentry = types.setdefault(tcode, {"code": tcode, "title": t.get("title") or tcode.title(),
                                              "match": MATCH_KEYS.get(tcode, tcode.lower()), "categories": {}})
            for sp in t.get("stateroomsPricing", []):
                title = (sp.get("stateroom") or {}).get("title")
                for cp in sp.get("categoryPricing", []):
                    so = cp.get("standardOption") or {}
                    code = so.get("pricedCategoryCode")
                    if not code:
                        continue
                    cat = tentry["categories"].setdefault(code, {
                        "code": code,
                        "title": title or code,
                        "guarantee": code in GUARANTEE_CODES or bool(so.get("isGTY")),
                        "solo": code in SOLO_CODES or (title or "").lower().startswith("solo"),
                        "capacity": None,
                        "by_guests": {},
                    })
                    if g == 2:
                        # Capacity only from the 2-guest call: it reads 0 whenever a category is unavailable.
                        cap = so.get("guestCapacity")
                        cat["capacity"] = cap if isinstance(cap, int) and cap > 0 else None
                    price = so.get("price")
                    available = bool(cp.get("isAvailable")) and isinstance(price, (int, float)) and price > 0
                    entry = {"available": available, "sold_out": bool(cp.get("isSoldOut"))}
                    if available:
                        entry["price_pp"] = int(round(price))
                        entry["cabin_total"] = entry["price_pp"] * g
                        if not cat["solo"] and (cheapest is None or price < cheapest[2]):
                            cheapest = (tcode, code, price)
                    cat["by_guests"][str(g)] = entry
        if cheapest is None:
            raise RuntimeError(f"No cabin is available on the {cfg['ship']} for {g} guests")
        tcode, ccode, _ = cheapest
        fare_code = fare_codes.get(tcode)
        if not fare_code:
            raise RuntimeError(f"No Free at Sea promotion code found for {cfg['ship']} {tcode}")
        summaries.append(fetch_price_summary(cfg, g, tcode, ccode, fare_code))
        log(f"  {g} guests: cheapest {ccode} ({tcode}), price summary {summaries[-1]['grand_total']}")

    # Fill in categories that were missing from some calls, and the reasons.
    for t in types.values():
        for cat in t["categories"].values():
            two = cat["by_guests"].get("2", {})
            for g in GUEST_COUNTS:
                e = cat["by_guests"].setdefault(str(g), {"available": False, "sold_out": False})
                if e["available"]:
                    if g > 2 and two.get("available"):
                        e["added_vs_2"] = e["cabin_total"] - two["cabin_total"]
                    continue
                if e["sold_out"]:
                    e["reason"] = "Sold out"
                elif cat["capacity"] is not None and cat["capacity"] < g:
                    e["reason"] = f"Holds only {cat['capacity']} guests"
                elif cat["capacity"] is not None:
                    e["reason"] = "Sold out for this party size"
                else:
                    e["reason"] = f"Not available for {g} guests"
            # Cross check: the extra guest price should be the same for guests 3, 4 and 5.
            if two.get("available"):
                per_extra = {g: (cat["by_guests"][str(g)]["cabin_total"] - two["cabin_total"]) / (g - 2)
                             for g in GUEST_COUNTS[1:] if cat["by_guests"][str(g)]["available"]}
                if len(per_extra) > 1 and max(per_extra.values()) - min(per_extra.values()) > TOLERANCE:
                    checks["extra_guest_mismatches"].append({
                        "sailing": cfg["id"], "category": cat["code"],
                        "per_extra_guest": {str(k): round(v, 2) for k, v in per_extra.items()},
                    })

    # Gratuities and taxes per guest, from the 2-guest price summary.
    s2 = summaries[0]
    gratuities = {}
    for key in ("open_bar", "specialty_dining"):
        line = s2[key]
        if not line or not line["per_guest"]:
            raise RuntimeError(f"No {key} gratuity in the {cfg['ship']} price summary")
        gratuities[key] = {"title": line["title"], "per_guest": line["per_guest"][0]}
    taxes = s2["taxes_per_guest"]
    if not taxes:
        raise RuntimeError(f"No tax line in the {cfg['ship']} price summary")

    # Cross check: availability price x guests + gratuities x guests = price summary total.
    for s in summaries:
        g = s["guests"]
        cat = next(c for t in types.values() for c in t["categories"].values() if c["code"] == s["category"])
        expected = cat["by_guests"][str(g)]["cabin_total"] + g * (gratuities["open_bar"]["per_guest"] + gratuities["specialty_dining"]["per_guest"])
        ok = abs(expected - s["grand_total"]) <= TOLERANCE
        checks["formula"].append({"sailing": cfg["id"], "guests": g, "category": s["category"],
                                  "expected": expected, "ncl_total": s["grand_total"], "ok": ok})

    out_types = []
    for t in types.values():
        cats = sorted(t["categories"].values(), key=lambda c: (c["by_guests"]["2"].get("price_pp") or 10 ** 9, c["code"]))
        out_types.append({"code": t["code"], "title": t["title"], "match": t["match"], "categories": cats})
    return {
        "id": cfg["id"],
        "ship": cfg["ship"],
        "ship_short": cfg["ship_short"],
        "itinerary_code": cfg["itinerary_code"],
        "package_id": cfg["package_id"],
        "depart": cfg["depart"],
        "return": ports[-1]["date"],
        "nights": nights,
        "url": f"https://www.ncl.com/cruises/{cfg['itinerary_code']}",
        "source": "NCL vacation-builder API",
        "saved_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d"),
        "taxes_per_guest": taxes[0],
        "gratuities": gratuities,
        "terminal": TERMINAL,
        "ports": ports,
        "price_summaries": summaries,
        "types": out_types,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    checks = {"extra_guest_mismatches": [], "formula": []}
    sailings = [fetch_sailing(cfg, checks) for cfg in SAILINGS]
    out = {
        "schema_version": SCHEMA_VERSION,
        "saved_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "NCL vacation-builder API (stateroom-types-availability and price-summary)",
        "guest_counts": GUEST_COUNTS,
        "checks": checks,
        "sailings": sailings,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
        f.write("\n")
    log(f"Wrote {args.out}")

    for m in checks["extra_guest_mismatches"]:
        log(f"Note: extra guest price differs for {m['sailing']} {m['category']}: {m['per_extra_guest']}")
    bad = [c for c in checks["formula"] if not c["ok"]]
    for c in bad:
        log(f"FORMULA CHECK FAILED: {c['sailing']} {c['category']} at {c['guests']} guests: "
            f"expected {c['expected']}, NCL total {c['ncl_total']}")
    if bad:
        sys.exit(1)


if __name__ == "__main__":
    main()
