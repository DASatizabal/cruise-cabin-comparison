#!/usr/bin/env python3
"""Florida resident fare proof for June (item 9, on hold): do June's fares differ when signed in?

MANUAL ONLY. It makes 14 NCL API calls, 6 of them signed in to the owner's NCL account, and
must NEVER run on a schedule (no Task Scheduler task, no GitHub workflow, no wrapper). It
writes nothing and commits nothing: it prints numbers only.

Calls, once per run: per ship 1 anonymous availability (2 guests), then for the cheapest
available non-Guarantee Inside, Balcony and Club Balcony Suite category 1 anonymous and 1
signed-in price summary (2 guests): 2 + 6 + 6 = 14. The signed-in browser also opens the
ncl.com home page once (a page load, not an API call), as Joy's runner does.

Guards: June's address check (fetch_prices.FORBIDDEN) on every address and hold_signal() on
every answer (request() for the anonymous calls, the same checks here for the signed-in ones;
the only exception is fetch_prices' HOLD payment option). The run stops on either. It reads
only the login token's expiry from the account, never a name, email or number.

Before running: Joy's "Joy Florida rates" task runs at 7:00 AM, 11:00 AM, 3:00 PM and 7:00 PM.
Run between those times. If the profile is in use the script waits 2 minutes, up to 3 times,
then exits with no NCL calls.

  py -3 tools\florida_proof.py

First run 2026-10-15 5:33 PM ET: all 6 differences $0 (NOTES.md, "Florida resident rates").
"""
import base64
import datetime as dt
import json
import os
import subprocess
import sys
import time
from urllib.parse import unquote

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE = r"D:\AI-VAULT\ncl-profile"   # the signed-in profile Joy's runner uses (never in a repo)
sys.path.insert(0, os.path.join(REPO, "tools"))
import fetch_prices as fp  # noqa: E402

GUESTS = 2
HOME = "https://www.ncl.com/"
TYPES = ["INSIDE", "BALCONY", "MINISUITE"]
calls = {"anonymous availability": 0, "anonymous price summary": 0, "signed-in price summary": 0}


def stamp():
    return dt.datetime.now(fp.MIAMI).strftime("%Y-%m-%d %I:%M:%S %p ET")


def profile_busy():
    lock = os.path.join(PROFILE, "lockfile")
    if os.path.exists(lock):
        try:
            with open(lock, "a"):
                pass
        except OSError:
            return "the profile's Chrome lockfile is in use"
    r = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-ScheduledTask -TaskName 'Joy Florida rates').State"],
                       capture_output=True, text=True)
    if r.stdout.strip() == "Running":
        return "the Joy Florida rates task is running"
    return None


def num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def fare_pp(res):
    """Fare per guest = (subtotal minus the Open Bar and Specialty Dining lines) / 2, checked:
    fare + taxes + those lines = NCL's grand total (within $1)."""
    lines = {}
    for group in res["staterooms"][0]["pricing"]["priceGroups"]:
        for item in group.get("priceItems", []):
            if item.get("itemType") == "strikethrough" or not item.get("guests"):
                continue
            lines[item["code"]] = [g.get("price") for g in item["guests"] if num(g.get("price"))]
    grat = sum(sum(v) for c, v in lines.items() if c.startswith("unlimited-open-bar") or c.startswith("specialty-dining"))
    tot = res.get("total") or {}
    taxes = sum(lines["taxes-and-fees"]) if lines.get("taxes-and-fees") else tot.get("taxesAndFees")
    if not num(tot.get("subtotal")) or not num(taxes) or not num(tot.get("grandTotal")):
        raise RuntimeError("no subtotal, tax line or grand total")
    fare = tot["subtotal"] - grat
    if fare <= 0 or abs(fare + taxes + grat - tot["grandTotal"]) > 1:
        raise RuntimeError(f"fare {fare} + taxes {taxes} + gratuities {grat} != total {tot['grandTotal']}")
    return round(fare / GUESTS, 2)


def body(cfg, type_code, code, fare_code):
    return {"packageId": cfg["package_id"],
            "stateroomFilters": [{"id": "0", "mainCabin": True, "numberOfGuests": GUESTS, "stateroomTypeCode": type_code,
                                  "pricedCategoryCode": code, "fareCodes": [fare_code], "guests": [], "vouchers": []}],
            "userFareCodes": []}


def signed_in_post(page, url, b):
    if fp.FORBIDDEN.search(url):
        raise RuntimeError(f"Refusing to call {url}: it could hold a cabin")
    time.sleep(fp.PAUSE_SECONDS)
    calls["signed-in price summary"] += 1
    r = page.evaluate("""async ({url, body}) => {
        const res = await fetch(url, {method: "POST", credentials: "include", redirect: "manual",
            headers: {"Content-Type": "application/json", "Accept": "application/json"}, body: JSON.stringify(body)});
        return {status: res.status, text: await res.text()};
    }""", {"url": url, "body": b})
    if r["status"] != 200:
        raise RuntimeError(f"NCL answered HTTP {r['status']} (signed in)")
    parsed = json.loads(r["text"])
    allowed = []
    signal = fp.hold_signal(parsed, price_summary=True, allowed=allowed)
    if signal:
        raise fp.HoldSignal(f"NCL's signed-in answer shows a hold signal ({signal}); stopping")
    if allowed:
        print(f"    {fp.PAYMENT_HOLD_NOTE}")
    return parsed


def login_state(ctx):
    """Reads only the login token's expiry, never the name or email in it."""
    for c in ctx.cookies(HOME):
        if c["name"] == "NCLAuth":
            try:
                token = json.loads(unquote(c["value"])).get("accessToken") or ""
                p = token.split(".")[1]
                exp = json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4))).get("exp")
                when = dt.datetime.fromtimestamp(exp, dt.timezone.utc)
                return when > dt.datetime.now(dt.timezone.utc), when.strftime("%Y-%m-%d")
            except Exception:
                return False, "unreadable"
    return False, "no login cookie"


def main():
    print(f"[{stamp()}] June Florida proof step")
    if os.path.abspath(PROFILE).startswith(REPO):
        raise SystemExit("The profile folder must not be inside the repository.")
    if dt.datetime.now(fp.MIAMI).date() >= dt.date(2027, 6, 11):
        print("The first sailing has left (Jun 11, 2027); nothing to check. No NCL calls made.")
        return 0
    for attempt in range(4):
        busy = profile_busy()
        if not busy:
            break
        if attempt == 3:
            print(f"Profile still busy ({busy}) after 3 waits. No NCL calls made.")
            return 9
        print(f"Profile busy ({busy}); waiting 2 minutes ({attempt + 1} of 3)")
        time.sleep(120)

    prices = json.loads(subprocess.run(["git", "-C", REPO, "show", "origin/main:data/prices.json"],
                                       capture_output=True, text=True, encoding="utf-8", check=True).stdout)
    plan = []
    for cfg in fp.SAILINGS:
        s = next(x for x in prices["sailings"] if x["id"] == cfg["id"])
        cfg = dict(cfg, itinerary_code=s["itinerary_code"], package_id=s["package_id"])
        calls["anonymous availability"] += 1
        result = fp.fetch_availability(cfg, GUESTS)
        codes = fp.default_fare_codes(result)
        best = {}
        for t in result.get("stateroomTypesPricing", []):
            if t["code"] not in TYPES:
                continue
            for sp in t.get("stateroomsPricing", []):
                title = ((sp.get("stateroom") or {}).get("title") or "").lower()
                for cp in sp.get("categoryPricing", []):
                    so = cp.get("standardOption") or {}
                    code, price = so.get("pricedCategoryCode"), so.get("price")
                    if not code or code in fp.SOLO_CODES or title.startswith("solo") or code in fp.GUARANTEE_CODES or so.get("isGTY"):
                        continue
                    if cp.get("isAvailable") and num(price) and price > 0 and (t["code"] not in best or price < best[t["code"]][1]):
                        best[t["code"]] = (code, price)
        for tc in TYPES:
            if tc in best:
                plan.append((cfg, tc, best[tc][0], codes[tc]))
            else:
                print(f"  {cfg['ship_short']} {tc}: nothing available (no call)")

    anon = {}
    for cfg, tc, code, fc in plan:
        calls["anonymous price summary"] += 1
        anon[(cfg["id"], code)] = fare_pp(fp.request(fp.PRICE_SUMMARY_URL, body(cfg, tc, code, fc)))

    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    ctx = pw.chromium.launch_persistent_context(PROFILE, channel="chrome", headless=True, viewport={"width": 1280, "height": 900})
    rows = []
    try:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(HOME, wait_until="domcontentloaded")
        ok, expires = login_state(ctx)
        if not ok:
            print(f"NOT SIGNED IN ({expires}). Stopping before any signed-in call.")
            return 2
        print(f"  Signed in (login expires {expires}).")
        for cfg, tc, code, fc in plan:
            florida = fare_pp(signed_in_post(page, fp.PRICE_SUMMARY_URL, body(cfg, tc, code, fc)))
            rows.append((cfg["ship_short"], tc, code, anon[(cfg["id"], code)], florida))
    finally:
        ctx.close()
        pw.stop()

    print(f"[{stamp()}] Results, 2 guests, fare per guest (subtotal minus Open Bar and Specialty Dining, / 2):")
    for ship, tc, code, web, fl in rows:
        print(f"  {ship:8} {tc:10} {code:3} website ${web:>9,.2f}  signed in ${fl:>9,.2f}  difference ${web - fl:>8,.2f}")
    print("NCL API calls: " + ", ".join(f"{k} {v}" for k, v in calls.items()) + f"; total {sum(calls.values())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
