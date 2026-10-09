#!/usr/bin/env python3
"""Count cabins left per category and party size, separately from prices.

Writes data/counts.new.json; the workflow format checks it (tools/check_counts.py) and only
then replaces data/counts.json. Prices never depend on this file: if it fails, the page keeps
the last good counts (and hides them once they are more than 7 days old).

  python3 tools/fetch_counts.py --prices data/prices.json --previous data/counts.json \\
      --out data/counts.new.json --mode auto

Modes:
  full   every available non-Guarantee category at every party size (about 140 calls)
  light  only categories whose last reliable count was under 15, plus the next pricier
         category each one needs for the subtraction; everything else keeps its last count
  auto   full when there is no usable previous file or the last full sweep was 3 or more
         days ago (by UTC date), light otherwise

Method (see NOTES.md, "Cabin counts"): NCL's cabin/availability call for a category returns it
plus every pricier category of the same broad type, with per location totals (numberOfCabins).
Cabin lists and deck counts are capped at 15 per deck, so only location totals are used. A
category's count = its call's location totals minus those of the call for the next pricier
non-Guarantee category. A count is unreliable (stored as null) when its call returns a category
or a location lowestPriceCategory from another broad type, when it ties in price with another
category, or when the subtraction is not positive. Guarantee cabins have no count.

Calls are 3 seconds apart, POST requests never follow redirects, redirects, 5xx and network
errors are retried after 30, 60 and 120 seconds, the address guard against "manage-cabin" and
"hold" applies, and the run stops if an answer mentions "hold" or "heldUntil".
"""
import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_prices as fp  # noqa: E402  (request, guards, URLs, sailings)
import check_counts  # noqa: E402

SCHEMA_VERSION = 1
PAUSE_SECONDS = 3
FULL_SWEEP_EVERY_DAYS = 3
LIGHT_RECHECK_BELOW = 15
GUEST_KEYS = ["2", "3", "4", "5"]


def now_utc():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


def load_json(path):
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def choose_mode(requested, previous, now):
    if previous is None:
        return "full", "no usable previous counts file"
    if requested == "full":
        return "full", "requested"
    if requested == "light":
        return "light", "requested"
    days = (now.date() - parse_iso(previous["last_full_sweep"]).date()).days
    if days >= FULL_SWEEP_EVERY_DAYS:
        return "full", f"last full sweep was {days} days ago"
    return "light", f"last full sweep was {days} day(s) ago"


def fetch_itinerary_sailing(cfg):
    """Sailing details for cabin/availability, from NCL's public itinerary call."""
    it = fp.request(fp.ITINERARY_URL.format(code=cfg["itinerary_code"], package_id=cfg["package_id"]))
    s = it.get("sailing") or {}
    if str(s.get("packageId")) != cfg["package_id"] or not (s.get("sailStartDate") or "").startswith(cfg["depart"]):
        raise RuntimeError(f"NCL's itinerary for {cfg['itinerary_code']} does not match packageId {cfg['package_id']} on {cfg['depart']}")
    return {
        "packageId": cfg["package_id"],
        "shipCode": (it.get("ship") or {}).get("code"),
        "departureDate": s["sailStartDate"],
        "destinationCodes": [d.get("code") for d in it.get("destinations") or [] if d.get("code")],
        "duration": it.get("duration"),
        "packageType": "CRUISE",
        "sailingId": str(s.get("sailingId")),
    }


def cabin_call(cfg, sailing, type_code, codes, cat_code, guests):
    """One cabin/availability call: location totals, foreign codes seen, and this code's own open cabins."""
    body = {"stateroomSearchFilter": {
        "stateroomTypeCode": type_code, "numberOfGuests": guests, "pricedCategoryCode": cat_code,
        "accessibilityRequested": False, "filterId": "0", "sailing": sailing, "guests": []}}
    res, raw = fp.request(fp.CABIN_AVAILABILITY_URL, body, raw=True)
    if fp.HOLD_IN_RESPONSE.search(raw):
        raise RuntimeError(f"cabin/availability for {cfg['ship']} {cat_code} mentioned a hold; stopping")
    locations = ((res or {}).get("results") or {}).get("availablePositionInShip") or []
    totals = {loc.get("name"): int(loc.get("numberOfCabins") or 0) for loc in locations}
    cabins = [cab for loc in locations for dk in loc.get("decks") or [] for cab in dk.get("cabins") or []]
    foreign = sorted(({loc.get("lowestPriceCategory") for loc in locations}
                      | {cab.get("pricedCategoryCode") for cab in cabins}) - set(codes) - {None})
    own = [cab for cab in cabins if cab.get("pricedCategoryCode") == cat_code]
    return {"totals": totals, "foreign": foreign, "own": own}


def open_cabins(own):
    """Where this code's own open cabins are, exactly as NCL lists them (never guessed)."""
    decks = sorted({int(c["deckNumber"]) for c in own if str(c.get("deckNumber", "")).isdigit()})
    locs = [fp.LOCATION_WORDS[l] for l in fp.LOCATION_ORDER if any(c.get("shipLocation") == l for c in own)]
    return decks or None, locs or None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prices", required=True, help="the current data/prices.json (categories and prices)")
    ap.add_argument("--previous", help="the current data/counts.json, if any")
    ap.add_argument("--out", required=True)
    ap.add_argument("--mode", choices=["auto", "full", "light"], default="auto")
    args = ap.parse_args()

    fp.PAUSE_SECONDS = PAUSE_SECONDS
    now = now_utc()
    prices = load_json(args.prices)
    if not prices or not prices.get("sailings"):
        raise SystemExit(f"Cannot read {args.prices}")
    previous = load_json(args.previous)
    if previous is not None and check_counts.check(previous):
        fp.log("Previous counts file is not valid; doing a full sweep")
        previous = None
    mode, why_mode = choose_mode(args.mode, previous, now)
    fp.log(f"Mode: {mode} ({why_mode})")

    out_sailings, calls, rechecked = {}, 0, 0
    for s in prices["sailings"]:
        cfg = next(c for c in fp.SAILINGS if c["id"] == s["id"])
        prev_s = (previous or {}).get("sailings", {}).get(s["id"], {}) if mode == "light" else {}
        out = {}
        # Start from the previous entries (light mode) for categories still available today.
        for t in s["types"]:
            for c in t["categories"]:
                if c["solo"] or c["guarantee"]:
                    continue
                p = prev_s.get(c["code"])
                entry = {"open_decks": (p or {}).get("open_decks"), "open_locations": (p or {}).get("open_locations"), "by_guests": {}}
                for g in GUEST_KEYS:
                    if c["by_guests"][g]["available"] and p and g in p.get("by_guests", {}):
                        entry["by_guests"][g] = p["by_guests"][g]
                out[c["code"]] = entry
        sailing = None
        for g in GUEST_KEYS:
            n = int(g)
            for t in s["types"]:
                codes = [c["code"] for c in t["categories"]]
                cats = [c for c in t["categories"] if not c["solo"] and not c["guarantee"] and c["by_guests"][g]["available"]]
                cats.sort(key=lambda c: c["by_guests"][g]["price_pp"], reverse=True)
                if not cats:
                    continue
                if mode == "full":
                    targets = [c["code"] for c in cats]
                else:
                    targets = [c["code"] for c in cats
                               if (out[c["code"]]["by_guests"].get(g) or {}).get("reliable")
                               and out[c["code"]]["by_guests"][g]["cabins_left"] < LIGHT_RECHECK_BELOW]
                if not targets:
                    continue
                order = [c["code"] for c in cats]
                needed = set(targets)
                for code in targets:
                    i = order.index(code)
                    if i > 0:
                        needed.add(order[i - 1])   # the next pricier category, for the subtraction
                if sailing is None:
                    sailing = fetch_itinerary_sailing(cfg)
                results = {}
                for code in order:              # most expensive first
                    if code in needed:
                        results[code] = cabin_call(cfg, sailing, t["code"], codes, code, n)
                        calls += 1
                prices_now = [c["by_guests"][g]["price_pp"] for c in cats]
                for code in targets:
                    i = order.index(code)
                    r = results[code]
                    prev_tot = results[order[i - 1]]["totals"] if i > 0 else {}
                    by_loc = {k: r["totals"].get(k, 0) - prev_tot.get(k, 0) for k in set(r["totals"]) | set(prev_tot)}
                    count = sum(by_loc.values())
                    why = None
                    if r["foreign"]:
                        why = f"call returned other cabin types: {', '.join(r['foreign'])}"
                    elif prices_now.count(cats[i]["by_guests"][g]["price_pp"]) > 1:
                        why = "ties in price with another category"
                    elif any(v < 0 for v in by_loc.values()) or count <= 0:
                        why = f"subtraction gave {dict(sorted(by_loc.items()))}"
                    out[code]["by_guests"][g] = {"cabins_left": None if why else count, "reliable": why is None,
                                                 "why": why, "checked_at": iso(now)}
                    rechecked += 1
                    if g == "2":
                        out[code]["open_decks"], out[code]["open_locations"] = open_cabins(r["own"])
            fp.log(f"  {cfg['ship_short']} {g} guests done ({calls} calls so far)")
        out_sailings[s["id"]] = {code: e for code, e in out.items() if e["by_guests"] or e["open_decks"] or e["open_locations"]}

    unreliable = [{"sailing": sid, "category": code, "guests": g, "why": e["why"]}
                  for sid, cats in out_sailings.items() for code, c in cats.items()
                  for g, e in sorted(c["by_guests"].items()) if not e["reliable"]]
    data = {
        "schema_version": SCHEMA_VERSION,
        "saved_at": iso(now),
        "mode": mode,
        "mode_reason": why_mode,
        "last_full_sweep": iso(now) if mode == "full" else previous["last_full_sweep"],
        "prices_saved_at": prices.get("saved_at"),
        "pause_seconds": PAUSE_SECONDS,
        "calls": calls,
        "rechecked": rechecked,
        "unreliable": unreliable,
        "sailings": out_sailings,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.write("\n")
    fp.log(f"Wrote {args.out}: {mode} mode, {calls} calls, {rechecked} counts checked, {len(unreliable)} unreliable")


if __name__ == "__main__":
    main()
