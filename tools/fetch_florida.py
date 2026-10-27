#!/usr/bin/env python3
"""Florida resident fares for June (item 9, 5.1.0): a light weekly check on the owner's AI PC.

Runs on the AI PC only, from a separate clone (D:\\Repos\\cruise-cabin-comparison) with the
browser profile that stays signed in to the owner's Florida resident NCL account. Setup and
steps for the owner: tools/florida-runner/README.md.

  py -3 tools\\fetch_florida.py --setup    sign in by hand (no NCL API calls)
  py -3 tools\\fetch_florida.py --push     the scheduled run: gets the latest main, checks only
                                          when a check is due, writes data/florida.json,
                                          commits and pushes it to main (publishes the page)
  py -3 tools\\fetch_florida.py            the same without committing (writes the file only)

Cadence (NOTES.md, "Florida resident rates"). Days are Eastern dates (America/New_York).
  - Light check, when the last check is 7 or more days old and found no discount: per ship 1
    anonymous availability call, then for the cheapest available non-Guarantee Inside,
    Oceanview, Balcony, Club Balcony Suite and Haven category 1 anonymous and 1 signed-in
    price summary at 2 guests. 2 + 10 + 10 = 22 calls, 10 signed in.
  - Full check, the same day, only when a light check finds a real discount ($1 or more off per
    guest on any cabin): every available cabin at 2 guests on both ships (the light check's
    cabins are not asked again). While a discount is active the full check repeats every 7
    days; when a full check finds no discount, the next check is a light one again.
  - Cabins that failed in a full check are retried on that day and the next (2 calls each,
    plus 1 availability call per ship); after that they wait for the next weekly check.
  - Runs that aren't due make no NCL calls. Nothing runs from the first sail date, Jun 11, 2027.

The page takes each cabin's own difference off the fare of guests 1 and 2 (dollar amounts per
category, as NCL gave them on the Joy page, never a percentage). A Florida fare higher than the
website fare counts as no discount.

Guards, before any NCL call: the profile is not in use (Chrome's lockfile, the Joy Florida rates
task not running and not due within 20 minutes); with --push, this clone is on main and its Git
email is GitHub's noreply address. On every call: June's address check (fetch_prices.FORBIDDEN)
and hold_signal() on every answer, anonymous (fetch_prices.request) and signed in (here); the
only exception is the HOLD payment option in price summaries. A hold signal stops the run.
data/florida.json holds numbers, codes and dates only (tools/check_florida.py rejects anything
else, public repo). It reads only the login token's expiry, never a name, email or number.
"""
import argparse
import base64
import datetime as dt
import json
import os
import subprocess
import sys
import time
from urllib.parse import unquote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_florida  # noqa: E402
import fetch_prices as fp  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRICES = os.path.join(ROOT, "data", "prices.json")
OUT = os.path.join(ROOT, "data", "florida.json")
DEFAULT_PROFILE = r"D:\AI-VAULT\ncl-profile"   # the signed-in profile, shared with Joy's runner (never in a repo)
SCHEMA_VERSION = 1
GUESTS = 2
HOME = "https://www.ncl.com/"
LIGHT_TYPES = ["INSIDE", "OCEANVIEW", "BALCONY", "MINISUITE", "HAVEN"]
FULL_TYPES = {"INSIDE", "OCEANVIEW", "BALCONY", "MINISUITE", "SUITE", "HAVEN"}
CADENCE_DAYS = 7          # a check is due when the last one is this many Eastern days old
RETRY_DAYS = 1            # failed cabins of a full check are retried on its day and the next
DISCOUNT_MIN = 1.0        # dollars off per guest that count as a discount (Joy showed $0.50 noise)
LAST_DAY = dt.date(2027, 6, 11)   # first sail date (Eastern): no checks from this day on
JOY_TASK = "Joy Florida rates"
JOY_GAP_MINUTES = 20      # never start when Joy's next run is this close
BUSY_WAITS = 3            # waits of 2 minutes while the profile is in use
LOGGED_IN = check_florida.SOURCE
NOREPLY = "174554998+DASatizabal@users.noreply.github.com"   # GitHub's private address for the owner
SOURCE = "NCL price-summary while signed in to a Florida resident NCL account (owner's AI PC)"
calls = {"anonymous availability": 0, "anonymous price summary": 0, "signed-in price summary": 0}


def log(msg):
    print(msg, flush=True)


def now_utc():
    """The current time (one place, so tests can set the clock)."""
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def eastern_date(text_or_time):
    """Calendar date in Miami (America/New_York, EDT or EST as that day has it), never the UTC
    date: after Nov 1 a 7:00 PM Eastern time is the next UTC day."""
    if isinstance(text_or_time, str):
        text_or_time = dt.datetime.strptime(text_or_time, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    return text_or_time.astimezone(fp.MIAMI).date()


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def git(*args, check=False):
    return subprocess.run(["git", "-C", ROOT, *args], capture_output=True, text=True, check=check)


# ---------- what is due ----------

def has_discount(data):
    return any(e["off_pp"] >= DISCOUNT_MIN for s in (data or {}).get("sailings", {}).values()
               for e in s.get("categories", {}).values())


def plan(prev, today):
    """(what, reason): what is "light", "full", "retry" or None (nothing due, no NCL calls)."""
    if not prev or check_florida.check(prev):
        return "light", "no usable previous check"
    last = dt.date.fromisoformat(prev["checked_on"])
    age = (today - last).days
    found = has_discount(prev)
    if prev["check"] == "light" and found:
        return "full", f"the light check on {last} found a discount"
    if age >= CADENCE_DAYS:
        if prev["check"] == "full" and found:
            return "full", f"a discount is active and the last full check was {last} ({age} days ago)"
        return "light", f"the last check was {last} ({age} days ago)"
    if prev["check"] == "full" and age <= RETRY_DAYS and any(s.get("missing") for s in prev["sailings"].values()):
        return "retry", f"some cabins of the full check on {last} failed"
    nxt = last + dt.timedelta(days=CADENCE_DAYS)
    return None, f"last check {last} ({prev['check']}, {'discount found' if found else 'no discount'}); next one due {nxt}"


# ---------- the profile ----------

def joy_next_run():
    """Local time of the Joy Florida rates task's next run, or None (no task, or not Windows)."""
    if os.name != "nt":
        return None
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
                        f"(Get-ScheduledTaskInfo -TaskName '{JOY_TASK}' -ErrorAction Stop).NextRunTime.ToString('yyyy-MM-ddTHH:mm:ss')"],
                       capture_output=True, text=True)
    try:
        return dt.datetime.fromisoformat(r.stdout.strip())
    except ValueError:
        return None


def profile_busy(profile):
    """Why the profile can't be used now, or None. Same checks as tools/florida_proof.py, plus
    Joy's next run: Chrome can open a profile in one program at a time."""
    lock = os.path.join(profile, "lockfile")
    if os.path.exists(lock):
        try:
            with open(lock, "a"):
                pass
        except OSError:
            return "the profile's Chrome lockfile is in use"
    if os.name == "nt":
        r = subprocess.run(["powershell", "-NoProfile", "-Command", f"(Get-ScheduledTask -TaskName '{JOY_TASK}' -ErrorAction SilentlyContinue).State"],
                           capture_output=True, text=True)
        if r.stdout.strip() == "Running":
            return f"the {JOY_TASK} task is running"
    nxt = joy_next_run()
    if nxt and dt.timedelta(0) <= nxt - dt.datetime.now() <= dt.timedelta(minutes=JOY_GAP_MINUTES):
        return f"the {JOY_TASK} task runs at {nxt:%I:%M %p}"
    return None


def wait_for_profile(profile):
    for attempt in range(BUSY_WAITS + 1):
        busy = profile_busy(profile)
        if not busy:
            return True
        if attempt == BUSY_WAITS:
            log(f"Profile still busy ({busy}) after {BUSY_WAITS} waits. No NCL calls made; the next run tries again.")
            return False
        log(f"Profile busy ({busy}); waiting 2 minutes ({attempt + 1} of {BUSY_WAITS})")
        time.sleep(120)


# ---------- NCL ----------

def num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def fare_pp(res):
    """Fare per guest = (subtotal minus the Open Bar and Specialty Dining lines) / 2, checked:
    fare + taxes + those lines = NCL's grand total (within $1). The same reading signed in and
    signed out (signed in, NCL lists no fare per guest; NOTES.md)."""
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
    """POST from inside the signed-in page, like NCL's own app. Address check before, hold_signal()
    after (HOLD payment option allowed, logged); a hold signal stops the run."""
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
        log(f"    {fp.PAYMENT_HOLD_NOTE}")
    return parsed


def login_state(ctx):
    """(signed_in, expiry date). Reads only the login token's expiry, never the name or email in it."""
    for c in ctx.cookies(HOME):
        if c["name"] == "NCLAuth":
            try:
                token = json.loads(unquote(c["value"])).get("accessToken") or ""
                p = token.split(".")[1]
                exp = json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4))).get("exp")
                when = dt.datetime.fromtimestamp(exp, dt.timezone.utc)
                return when > dt.datetime.now(dt.timezone.utc), when.astimezone(fp.MIAMI).date()
            except Exception:
                return False, "unreadable"
    return False, "no login cookie"


def available(result):
    """[(type, code, price, guarantee)] of every available category at 2 guests, cheapest first.
    Solo cabins and Studio are left out (hidden on the page)."""
    out = []
    for t in result.get("stateroomTypesPricing", []):
        if t["code"] not in FULL_TYPES:
            continue
        for sp in t.get("stateroomsPricing", []):
            title = ((sp.get("stateroom") or {}).get("title") or "").lower()
            for cp in sp.get("categoryPricing", []):
                so = cp.get("standardOption") or {}
                code, price = so.get("pricedCategoryCode"), so.get("price")
                if not code or code in fp.SOLO_CODES or title.startswith("solo"):
                    continue
                if cp.get("isAvailable") and num(price) and price > 0:
                    out.append((t["code"], code, price, code in fp.GUARANTEE_CODES or bool(so.get("isGTY"))))
    return sorted(out, key=lambda x: x[2])


def light_picks(avail):
    """The cheapest available non-Guarantee category of each light check type."""
    picks = []
    for tc in LIGHT_TYPES:
        best = next(((t, c) for t, c, p, gty in avail if t == tc and not gty), None)
        if best:
            picks.append(best)
    return picks


def open_browser(profile, show):
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    ctx = pw.chromium.launch_persistent_context(profile, channel="chrome", headless=not show, viewport={"width": 1280, "height": 900})
    return pw, ctx, (ctx.pages[0] if ctx.pages else ctx.new_page())


def check_cabin(page, cfg, type_code, code, fare_code):
    if not fare_code:
        raise RuntimeError(f"NCL listed no Free at Sea promotion for {type_code} (no call made)")
    b = body(cfg, type_code, code, fare_code)
    calls["anonymous price summary"] += 1
    website = fare_pp(fp.request(fp.PRICE_SUMMARY_URL, b))
    florida = fare_pp(signed_in_post(page, fp.PRICE_SUMMARY_URL, b))
    return {"type": type_code, "website_fare_pp": website, "florida_fare_pp": florida,
            "off_pp": round(website - florida, 2), "checked_at": iso(now_utc()), "source": LOGGED_IN}


def check_all(page, todo):
    """Checks each (sailing id, cfg, type, code, fare code). Returns ({id: {code: entry}}, {id: [failed codes]})."""
    got, failed = {}, {}
    for sid, cfg, tc, code, fc in todo:
        try:
            e = check_cabin(page, cfg, tc, code, fc)
        except fp.HoldSignal:
            raise
        except Exception as ex:
            failed.setdefault(sid, []).append(code)
            log(f"  {cfg['ship_short']} {code}: failed ({ex})")
            continue
        got.setdefault(sid, {})[code] = e
        log(f"  {cfg['ship_short']:8} {tc:10} {code:3} website ${e['website_fare_pp']:>9,.2f}  Florida ${e['florida_fare_pp']:>9,.2f}  off ${e['off_pp']:>8,.2f}")
    return got, failed


# ---------- publishing ----------

def clone_ok():
    """None when this clone may commit and push, else why not (checked before any NCL call)."""
    email = git("config", "user.email").stdout.strip()
    if email != NOREPLY:
        return (7, "Not publishing: this clone's Git email isn't GitHub's private noreply address, and the repo is public.\n"
                   f'Fix once, in {ROOT}: git config user.email "{NOREPLY}"')
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if branch != "main":
        return 8, f"Not publishing: this clone is on branch '{branch}'. It only ever pushes main: git switch main"
    return None


def publish(what):
    """Commit data/florida.json if it changed, and push main if it has anything new (also a
    commit an earlier run couldn't push). what ("light" or "full") goes in the commit message."""
    refused = clone_ok()
    if refused:
        log(refused[1])
        return refused[0]
    git("add", "data/florida.json", check=True)
    if git("diff", "--cached", "--quiet").returncode != 0:
        git("commit", "-q", "-m", f"Refresh Florida rates {eastern_date(now_utc())} ({what})", check=True)
    if git("rev-list", "--count", "origin/main..HEAD").stdout.strip() in ("", "0"):
        log("Nothing new to publish.")
        return 0
    for attempt in range(4):
        if git("pull", "--rebase", "-q", "origin", "main").returncode == 0 and \
           git("push", "-q", "origin", "HEAD:main").returncode == 0:
            log("Pushed to main; the page republishes in about a minute.")
            return 0
        time.sleep(2 ** (attempt + 1))
    log("Push failed. The file is saved here; run 'git push origin HEAD:main' by hand.")
    return 6


# ---------- runs ----------

def setup(profile):
    """Sign in by hand. Opens ncl.com only (a page load, no NCL API calls)."""
    if not wait_for_profile(profile):
        return 9
    pw, ctx, page = open_browser(profile, show=True)
    try:
        page.goto(HOME, wait_until="domcontentloaded")
        log("A Chrome window opened on ncl.com.")
        log("1. In that window, sign in to your NCL account (the one with your Florida address).")
        log("2. If NCL offers 'Remember me' or 'Keep me signed in', tick it.")
        input("3. When you see you're signed in, come back here and press Enter. ")
        ok, expires = login_state(ctx)
    finally:
        ctx.close()
        pw.stop()
    log(f"Signed in: {'yes' if ok else 'NO'} (login expires {expires})")
    return 0 if ok else 2


def run(profile, show, push):
    if push:
        refused = clone_ok()
        if refused:
            log(refused[1])
            return refused[0]
        if git("pull", "--rebase", "--autostash", "-q", "origin", "main").returncode != 0:
            log("Could not get the latest main from GitHub. No NCL calls made; the next run tries again.")
            return 6
    today = eastern_date(now_utc())
    log(f"[{now_utc().astimezone(fp.MIAMI):%Y-%m-%d %I:%M %p} ET] June Florida rates")
    if today >= LAST_DAY:
        log("The first sailing has left (Jun 11, 2027); nothing to check. No NCL calls made.")
        return 0
    prev = load_json(OUT)
    what, reason = plan(prev, today)
    if not what:
        log(f"Not due: {reason}. No NCL calls made.")
        # A file written by a run without --push (or a commit that couldn't be pushed) goes out now.
        return publish(prev["check"]) if push else 0
    log(f"Due: {what} check ({reason}).")
    if not wait_for_profile(profile):
        return 9

    prices = load_json(PRICES)
    if not prices or not prices.get("sailings"):
        log(f"Cannot read {PRICES}. No NCL calls made.")
        return 5
    ships = []
    for cfg in fp.SAILINGS:
        s = next(x for x in prices["sailings"] if x["id"] == cfg["id"])
        ships.append(dict(cfg, itinerary_code=s["itinerary_code"], package_id=s["package_id"]))
    keep = {}   # entries kept from this full check's earlier run (retry only)
    if what == "retry":
        keep = {sid: dict(s["categories"]) for sid, s in prev["sailings"].items()}
        ships = [c for c in ships if prev["sailings"].get(c["id"], {}).get("missing")]

    todo_light, todo_full, fare_codes, avail = [], [], {}, {}
    for cfg in ships:
        calls["anonymous availability"] += 1
        result = fp.fetch_availability(cfg, GUESTS)
        fare_codes[cfg["id"]], avail[cfg["id"]] = fp.default_fare_codes(result), available(result)
        if what == "light":
            todo_light += [(cfg["id"], cfg, t, c, fare_codes[cfg["id"]].get(t)) for t, c in light_picks(avail[cfg["id"]])]
        elif what == "retry":
            missing = set(prev["sailings"][cfg["id"]]["missing"])
            todo_full += [(cfg["id"], cfg, t, c, fare_codes[cfg["id"]].get(t)) for t, c, p, g in avail[cfg["id"]] if c in missing]
        else:
            todo_full += [(cfg["id"], cfg, t, c, fare_codes[cfg["id"]].get(t)) for t, c, p, g in avail[cfg["id"]]]

    got, failed = {}, {}
    todo = todo_light or todo_full
    if todo:
        pw, ctx, page = open_browser(profile, show)
        try:
            page.goto(HOME, wait_until="domcontentloaded")
            ok, expires = login_state(ctx)
            if not ok:
                log(f"NOT SIGNED IN ({expires}). Sign in again: README, 'When the login expires'. File not changed.")
                return 2
            log(f"Signed in (login expires {expires}).")
            if isinstance(expires, dt.date) and (expires - today).days <= 14:
                log(f"The NCL login expires on {expires}. Sign in again soon: README, 'When the login expires'.")
            got, failed = check_all(page, todo)
            if what == "light" and has_discount({"sailings": {sid: {"categories": c} for sid, c in got.items()}}):
                # A real discount: the full check of every cabin, today, so each one has its own amount.
                log("The light check found a Florida discount: checking every cabin on both ships now.")
                what = "full"
                done = {(sid, code) for sid, cats in got.items() for code in cats} | {(sid, c) for sid, cs in failed.items() for c in cs}
                rest = [(cfg["id"], cfg, t, c, fare_codes[cfg["id"]].get(t)) for cfg in ships for t, c, p, g in avail[cfg["id"]]
                        if (cfg["id"], c) not in done]
                more, more_failed = check_all(page, rest)
                for sid, cats in more.items():
                    got.setdefault(sid, {}).update(cats)
                for sid, codes in more_failed.items():
                    failed.setdefault(sid, []).extend(codes)
        finally:
            ctx.close()
            pw.stop()
    elif what == "retry":
        log("The failed cabins are no longer available at 2 guests; clearing the list (no signed-in calls).")
    else:
        log("NCL listed no available cabin to check. File not changed; the next run tries again.")
        return 4

    log("NCL API calls: " + ", ".join(f"{k} {v}" for k, v in calls.items()) + f"; total {sum(calls.values())}")
    n_failed = sum(len(v) for v in failed.values())
    if todo and not got:
        log("Every cabin checked this run failed. File not changed; the next run tries again.")
        return 4
    if what == "light" and n_failed:
        log(f"{n_failed} light check cabins failed and none of the others got a discount. File not changed; the next run repeats the light check.")
        return 4
    checked_on = prev["checked_on"] if what == "retry" else today.isoformat()
    data = {"schema_version": SCHEMA_VERSION, "saved_at": iso(now_utc()), "guests": GUESTS, "source": SOURCE,
            "check": "full" if what == "retry" else what, "checked_on": checked_on, "sailings": {}}
    packages = {c["id"]: c["package_id"] for c in ships}
    if what == "retry":
        for sid, s in prev["sailings"].items():
            packages.setdefault(sid, s["package_id"])
    for sid, package in packages.items():
        cats = dict(keep.get(sid, {}))
        cats.update(got.get(sid, {}))
        missing = sorted(set(failed.get(sid, [])) - set(cats)) if data["check"] == "full" else []
        data["sailings"][sid] = {"package_id": str(package), "categories": dict(sorted(cats.items())), "missing": missing}
    errors = check_florida.check(data)
    if errors:
        log("Format check failed, file not changed: " + "; ".join(errors))
        return 5
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
        f.write("\n")
    found = has_discount(data)
    log(f"Wrote {OUT}: {data['check']} check, {sum(len(v) for v in got.values())} cabins checked, {n_failed} failed, "
        + ("Florida discount found." if found else "no Florida discount."))
    return publish(data["check"]) if push else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=os.environ.get("NCL_PROFILE", DEFAULT_PROFILE),
                    help="browser profile folder that keeps the NCL login (never inside a repo)")
    ap.add_argument("--setup", action="store_true", help="sign in by hand (no NCL API calls)")
    ap.add_argument("--show", action="store_true", help="show the browser window during the run")
    ap.add_argument("--push", action="store_true", help="commit and push data/florida.json to main")
    args = ap.parse_args()
    if os.path.abspath(args.profile).startswith(ROOT):
        raise SystemExit("The profile folder must not be inside the repository.")
    if args.setup:
        return setup(args.profile)
    return run(args.profile, args.show, args.push)


if __name__ == "__main__":
    sys.exit(main())
