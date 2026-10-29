"""Chromium test of index.html at 360 px wide (no NCL calls). Needs Playwright:
    pip install playwright && python -m playwright install chromium
    python3 tools/page_test.py [folder for screenshots]

Two copies of the page are served from a temporary folder: one with today's data/prices.json and
one with the null copy from test_tools.null_copy (Getaway taxes and gratuities and every rate null,
each with its warning). Checks: no sideways scrolling, no script errors, "Prices as of" in Eastern
time with the time of day, the "Not found on NCL today" rules (NOTES.md, "Missing numbers"), and the
prepay gratuities switch (NOTES.md, "Prepay gratuities off by default"), and the Florida resident
rate switch with test copies of data/florida.json: no discount ("Selected..."), a Florida fare above
the website, amber after 9 days, not used after 15, a discount on both ships and on one, 4 guests,
and the switch off (NOTES.md, "Florida resident rates").

Make Selection (5.2.0, NOTES.md "Make Selection"): the window on every card at 360 px, the price
without gratuities (gratuities listed, not added), NCL's deposit and the 2-For-1 line, one and two
CruiseNext credits (DoubleUp from a test data/offers.json: on, read too long ago, ended, a cabin
type it doesn't cover), a Haven deposit (10% of the fare, a credit covering part of it), the
Florida answer overriding the page switch, 8 nights as two bookings with totals, the checks on
every field (a kid's date of birth that doesn't match the age on the page), a schema 3 price
file (deposit not found), and sending to a stand-in for the Worker (the request it gets, nothing
saved in the browser).

Layout (5.2.0): the option tiles at 360 px and 1280 px (none selected and the prompt on the first
visit, cards in tile order, side by side on a wide screen and stacked on a phone, remembered on
return, no sideways scrolling), every cabin list price equal to the card's Total for that cabin in
every switch combination, and the service charge line below the Total when not prepaid. Every
other check starts with all three tiles selected (new_page).
"""
import datetime as dt
import functools
import http.server
import json
import os
import re
import shutil
import sys
import tempfile
import threading
from zoneinfo import ZoneInfo

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = sys.argv[1] if len(sys.argv) > 1 else None
sys.stdout.reconfigure(errors="replace")   # the page's minus sign on a Windows console
sys.path.insert(0, os.path.join(REPO, "tools"))
import check_florida  # noqa: E402
import test_tools  # noqa: E402  (null_copy, schema4)

from playwright.sync_api import sync_playwright  # noqa: E402

MIAMI = ZoneInfo("America/New_York")

with open(os.path.join(REPO, "data", "prices.json"), encoding="utf-8") as f:
    real = json.load(f)
sites = {"real": test_tools.schema4(real), "nulls": test_tools.null_copy(real)}


def ksf_copy(data):
    """Kids Sail Free test copy: NCL lists the offer on both ships (Inside to Club Balcony Suite, as
    on the Joy page). The Getaway's BF prices for 3 and 4 guests are set so each extra guest pays
    only the taxes ("prices agree"); the Aura's prices are today's ("prices charge a fare")."""
    d = test_tools.schema4(data)
    offer = {"title": "Kids Sail Free", "short": "3rd & 4th guests sail free", "description": "test", "codes": ["34CHO"],
             "types": ["INSIDE", "OCEANVIEW", "BALCONY", "MINISUITE"], "checked_at": "2026-10-15T10:20:00Z"}
    for sl in d["sailings"]:
        sl["kids_sail_free"] = dict(offer)
    g = next(sl for sl in d["sailings"] if sl["id"].startswith("getaway"))
    bf = next(c for t in g["types"] for c in t["categories"] if c["code"] == "BF")
    two = bf["by_guests"]["2"]["cabin_total"]
    for n in (3, 4):
        e = bf["by_guests"][str(n)]
        e["cabin_total"] = two + (n - 2) * g["taxes_per_guest"]
        e["price_pp"] = round(e["cabin_total"] / n, 2)
    return d


def fl_copy(off, days_ago, skip=()):
    """A data/florida.json for the test: every cabin available at 2 guests on both ships, saved
    days_ago days before now, with the given dollars off per guest ((ship, code): amount)."""
    when = dt.datetime.now(dt.timezone.utc).replace(microsecond=0) - dt.timedelta(days=days_ago)
    at = when.strftime("%Y-%m-%dT%H:%M:%SZ")
    sailings = {}
    for s in real["sailings"]:
        cats = {}
        for t in s["types"]:
            if t["code"] == "STUDIO":
                continue
            for c in t["categories"]:
                e = c["by_guests"]["2"]
                if c["solo"] or not e["available"] or (s["ship_short"], c["code"]) in skip:
                    continue
                web = round((e["cabin_total"] - 2 * s["taxes_per_guest"]) / 2, 2)
                o = off.get((s["ship_short"], c["code"]), 0)
                cats[c["code"]] = {"type": t["code"], "website_fare_pp": web, "florida_fare_pp": round(web - o, 2), "off_pp": o,
                                   "checked_at": at, "source": "logged-in NCL account"}
        sailings[s["id"]] = {"package_id": s["package_id"], "categories": cats, "missing": []}
    d = {"schema_version": 1, "saved_at": at, "guests": 2, "source": "test", "check": "full",
         "checked_on": when.astimezone(MIAMI).date().isoformat(), "sailings": sailings}
    assert not check_florida.check(d), check_florida.check(d)
    e = when.astimezone(MIAMI)
    return d, f"{e:%b} {e.day}, {e.year}"


FL_SITES = {"none": fl_copy({}, 0), "higher": fl_copy({("Getaway", "BF"): -20}, 0), "old": fl_copy({}, 10),
            "stale": fl_copy({}, 16), "both": fl_copy({("Getaway", "BF"): 60, ("Aura", "B4"): 25}, 1, skip={("Getaway", "B4")}),
            "one": fl_copy({("Getaway", "BF"): 60}, 0)}
FL_SITES_WHEN = {k: v[1] for k, v in FL_SITES.items()}
for name in FL_SITES:
    sites[name] = test_tools.schema4(real)


sites["ksf"] = ksf_copy(real)
sites["ms_api"] = test_tools.schema4(real)   # Make Selection with a stand-in for the Worker
sites["schema3"] = real                       # the committed file until the first refresh after 5.2.0
FAMILY_API_TEST = "https://family-alerts.test"
site_root = tempfile.mkdtemp(prefix="june-page-")
for name, data in sites.items():
    d = os.path.join(site_root, name)
    os.makedirs(os.path.join(d, "data"))
    shutil.copy(os.path.join(REPO, "index.html"), d)
    if name == "ms_api":
        with open(os.path.join(d, "index.html"), encoding="utf-8") as f:
            html = f.read()
        assert 'const FAMILY_API = "";' in html and 'const TURNSTILE_SITE_KEY = "";' in html
        html = html.replace('const FAMILY_API = "";', f'const FAMILY_API = "{FAMILY_API_TEST}";').replace(
            'const TURNSTILE_SITE_KEY = "";', 'const TURNSTILE_SITE_KEY = "test-site-key";')
        with open(os.path.join(d, "index.html"), "w", encoding="utf-8") as f:
            f.write(html)
    counts = os.path.join(REPO, "data", "counts.json")
    if os.path.exists(counts):
        shutil.copy(counts, os.path.join(d, "data"))
    with open(os.path.join(d, "data", "prices.json"), "w", encoding="utf-8") as f:
        json.dump(data, f)
    if name in FL_SITES:
        with open(os.path.join(d, "data", "florida.json"), "w", encoding="utf-8") as f:
            json.dump(FL_SITES[name][0], f)

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


handler = functools.partial(Quiet, directory=site_root)
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_address[1]}"

money = lambda t: float(re.sub(r"[^\d.]", "", t))
fails = []


def console_error(m):
    """A console error, except the 404 of an optional file the page does without (florida.json:
    until the AI PC's first check, the page shows website prices; offers.json: until the first
    refresh after 5.2.0, Make Selection offers one CruiseNext credit)."""
    return m.type == "error" and not (m.location or {}).get("url", "").endswith(("/data/florida.json", "/data/offers.json"))


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}{(': ' + str(detail)) if detail else ''}")
    if not ok:
        fails.append(name)


def rows_of(card):
    """(label, amount) of each line in a card, in order."""
    return [(r.query_selector(".k").inner_text(), r.query_selector(".v").inner_text())
            for r in card.query_selector_all(".rows .row") if r.query_selector(".k") and r.query_selector(".v")]


def notes_of(card):
    return [n.inner_text() for n in card.query_selector_all(".notice.info")]


# "Prices as of": Eastern time (America/New_York) with the time of day, daylight saving time handled.
AS_OF_CASES = [
    ("2026-10-15T10:17:00Z", "Oct 15, 6:17 AM ET"),    # EDT, UTC-4
    ("2026-10-13T01:36:00Z", "Oct 12, 9:36 PM ET"),    # the evening run that is Oct 13 by UTC date
    ("2026-11-02T01:36:00Z", "Nov 1, 8:36 PM ET"),     # EST, UTC-5, after daylight saving time ends
    ("2027-03-15T16:05:00Z", "Mar 15, 12:05 PM ET"),   # EDT again
]

# Every check but the tile checks starts with all three option tiles selected: saved choices
# without tiles get all three, and a first visit gets the defaults with all three.
ALL_TILES = """(() => { try {
    for (const key of ["cruise-decision-guide-v5", "cruise-decision-guide-v4"]) {
        const s = JSON.parse(localStorage.getItem(key) || "null");
        if (s && !("compare" in s)) localStorage.setItem(key, JSON.stringify(Object.assign(s, { compare: ["G", "A", "8"] })));
    }
    if (!localStorage.getItem("cruise-decision-guide-v5") && !localStorage.getItem("cruise-decision-guide-v4"))
        localStorage.setItem("cruise-decision-guide-v5", JSON.stringify({ adults: 2, kids: [], type: "balcony", mode: "same", compare: ["G", "A", "8"] }));
} catch (e) {} })()"""

real_rows = {}
with sync_playwright() as pw:
    browser = pw.chromium.launch()

    def same(name, got, want):
        check(name, got == want, "" if got == want else f"got {got}, expected {want}")

    def new_page(viewport=None, tiles=True):
        page = browser.new_page(viewport=viewport or {"width": 360, "height": 800})
        if tiles:
            page.add_init_script(ALL_TILES)
        return page
    for name in ("real", "nulls"):
        page = new_page(viewport={"width": 360, "height": 800})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if console_error(m) else None)
        page.goto(f"{base}/{name}/index.html")
        page.wait_for_selector(".card .price-total")
        width = page.evaluate("Math.max(document.documentElement.scrollWidth, document.body.scrollWidth)")
        check(f"{name}: no sideways scrolling at 360 px", width <= 360, f"page width {width}")
        check(f"{name}: no script errors", not errors, errors[:3])

        as_of = page.inner_text("#asOf").replace(" ", " ")
        check(f"{name}: 'Prices as of' is a date and time in ET", re.fullmatch(r"[A-Z][a-z]{2} \d{1,2}, \d{1,2}:\d{2} [AP]M ET", as_of) is not None, as_of)
        if name == "real":
            for utc, want in AS_OF_CASES:
                got = page.evaluate("t => fmtEastern(t)", utc).replace(" ", " ")
                check(f"'Prices as of' for {utc}", got == want, got)

        cards = page.query_selector_all(".card")
        totals = [c.query_selector(".price-total").inner_text() for c in cards]
        print(f"      card totals: {totals}")
        text = page.inner_text("#app")
        nf = text.count("Not found on NCL today")
        if name == "real":
            real_rows = {"getaway": rows_of(cards[0]), "getaway_total": totals[0]}
            check("real: no 'Not found' lines", nf == 0, nf)
            check("real: no 'Not included' note", "Not included in the total" not in text)
            check("real: no tax split note", "per-guest tax split" not in text)
        else:
            check("nulls: 'Not found on NCL today' lines shown", nf > 0, f"{nf} lines")
            g, a, both = cards[0], cards[1], cards[2]
            gnotes, bnotes = notes_of(g), notes_of(both)
            for n in gnotes + bnotes:
                print("      note: " + n)
            left_out = [n for n in gnotes if "Not included" in n]
            check("nulls: Getaway card lists what isn't included",
                  len(left_out) == 1 and all(w in left_out[0] for w in ("service charges", "Open Bar", "Specialty Dining")), left_out)
            check("nulls: 8 night card names the ship for each item",
                  any("Getaway service charges" in n and "Aura service charges" in n for n in bnotes), bnotes)

            # Taxes with no tax line (option A): NCL's cabin price includes them, so they stay in
            # the total. The page must not say they are left out; it says the split wasn't shown.
            check("nulls: 'Not included' notes never name taxes",
                  not any("tax" in n.lower() for n in gnotes + bnotes if "Not included" in n), [n for n in gnotes + bnotes if "Not included" in n])
            check("nulls: Getaway card says the cabin price includes taxes and the split wasn't shown",
                  any("Getaway cabin price includes taxes, fees and port expenses, and they are in the total. NCL didn't show the per-guest tax split today." in n for n in gnotes), gnotes)
            check("nulls: 8 night card says the same for the Getaway only",
                  any(n.startswith("The Getaway cabin price includes taxes") for n in bnotes) and not any("Aura cabin price" in n for n in bnotes), bnotes)
            check("nulls: Aura card (tax line present) has no tax split note", not any("tax split" in n for n in notes_of(a)), notes_of(a))
            grows = rows_of(g)
            tax_row = [(k, v) for k, v in grows if k.startswith("Taxes")]
            check("nulls: Getaway tax row says 'Included above', not 'Not found'",
                  tax_row == [("Taxes, fees and port expenses (per-guest split not shown by NCL today)", "Included above")], tax_row)
            cabin = money(dict(grows)["Cruise fare with taxes, fees and port expenses"])
            r = dict(real_rows["getaway"])
            real_fare_taxes = money(r["Cruise fare"]) + money(next(v for k, v in real_rows["getaway"] if k.startswith("Taxes")))
            check("nulls: Getaway cabin price = today's fare + taxes for the same cabin (taxes still inside)",
                  abs(cabin - real_fare_taxes) < 0.01, f"{cabin} vs {r['Cruise fare']} + taxes = {real_fare_taxes}")
            check("nulls: Getaway total = NCL's cabin price (taxes included; gratuities and rates left out)",
                  money(totals[0]) == cabin, f"{totals[0]} vs {cabin}")

            arows = rows_of(a)
            parts = sum(money(v) for k, v in arows if k.startswith(("Cruise fare", "Taxes", "Unlimited Open Bar", "Specialty Dining")) and "$" in v)
            check("nulls: Aura total = fare + taxes + Open Bar + Specialty Dining", abs(money(totals[1]) - parts) < 0.01, f"{totals[1]} vs {parts}")
            check("nulls: Plus switch says its price wasn't found", "Price not found on NCL today, so it can't be added here." in text)
            check("nulls: 8 night total = Getaway + Aura totals", abs(money(totals[2]) - money(totals[0]) - money(totals[1])) < 0.01, totals)
        if SHOTS:
            os.makedirs(SHOTS, exist_ok=True)
            page.screenshot(path=os.path.join(SHOTS, f"{name}_360.png"), full_page=True)
        page.close()

    # Prepay gratuities switch (5.0.0): off by default; off = service charges out of every total,
    # on a line directly below the Total (5.2.0: "Service charges (crew gratuities) (paid onboard,
    # not in the total): 2 guests x $20 x 3 nights", "$60 onboard", one line per ship on the 8 night
    # card, "Can be removed at Guest Services." under it); on = in the totals. Today's data, 2 adults, Balcony.
    OFF_TITLE, ON_TITLE = "Prepay gratuities (No)", "Prepay gratuities"
    OFF_DESC = "Pay onboard on the last day. Service charges are not in the totals. They're charged to your onboard account and can be removed at Guest Services."
    ON_DESC = "Service charges are paid with the cruise, before you sail. The amount is the same either way."
    R = sites["real"]["rates"]["service_charge"]
    nights = {s["id"].split("-")[0]: s["nights"] for s in sites["real"]["sailings"]}
    want_onboard = [2 * R["standard_per_night"] * nights["getaway"], 2 * R["standard_per_night"] * nights["aura"]]
    want_onboard.append(want_onboard[0] + want_onboard[1])   # 8 nights: both ships' service charges

    fm = lambda x: f"${int(x):,}" if x == int(x) else f"${x:,.2f}"
    sc_part = lambda ship: f"2 guests x {fm(R['standard_per_night'])} x {nights[ship]} nights"
    want_lines = [[(f"Service charges (crew gratuities) (paid onboard, not in the total): {sc_part('getaway')}", f"{fm(want_onboard[0])} onboard")],
                  [(f"Service charges (crew gratuities) (paid onboard, not in the total): {sc_part('aura')}", f"{fm(want_onboard[1])} onboard")],
                  [(f"Getaway service charges (crew gratuities) (paid onboard, not in the total): {sc_part('getaway')}", f"{fm(want_onboard[0])} onboard"),
                   (f"Aura service charges (crew gratuities) (paid onboard, not in the total): {sc_part('aura')}", f"{fm(want_onboard[1])} onboard")]]

    def state(page):
        cards = page.query_selector_all(".card")
        return {"checked": page.is_checked("#prepayToggle"),
                "title": page.inner_text("#prepayLabel"), "desc": page.inner_text("#prepayDesc"),
                "totals": [money(c.query_selector(".price-total").inner_text()) for c in cards[:3]],
                "labels": [c.query_selector(".price-label").inner_text() for c in cards[:3]],
                "onboard": [[(r.query_selector(".k").inner_text(), r.query_selector(".v").inner_text()) for r in c.query_selector_all(".row.onboard")] for c in cards[:3]],
                # What follows the Total line: the onboard lines, then the small note, then the cost per night.
                "after_total": [c.eval_on_selector(".row.total", """t => { const out = []; for (let n = t.nextElementSibling; n; n = n.nextElementSibling)
                                    out.push(n.classList.contains("onboard-small") ? "note: " + n.textContent : n.classList.contains("onboard") ? "onboard" : n.querySelector(".k").textContent.split(" (")[0]); return out; }""")
                                for c in cards[:3]],
                "sc_in_breakdown": [[(k, v) for k, v in rows_of(c)[:rows_of(c).index(next(x for x in rows_of(c) if x[0] == "Total"))] if k.startswith(("Service charges", "Getaway service charges", "Aura service charges"))] for c in cards[:3]],
                "old_note": page.query_selector(".onboard-note") is not None,
                "text": page.inner_text("#app")}

    def is_off(st, where):
        check(f"prepay off ({where}): switch unchecked, title and subtitle", (st["checked"], st["title"], st["desc"]) == (False, OFF_TITLE, OFF_DESC), (st["checked"], st["title"], st["desc"]))
        same(f"prepay off ({where}): service charge line below the Total with the real numbers (8 nights: one per ship)", st["onboard"], want_lines)
        same(f"prepay off ({where}): directly below the Total, then 'Can be removed at Guest Services.', then the cost per night", st["after_total"],
             [["onboard", "note: Can be removed at Guest Services.", "Cost per night"], ["onboard", "note: Can be removed at Guest Services.", "Cost per night"],
              ["onboard", "onboard", "note: Can be removed at Guest Services.", "Cost per night"]])
        same(f"prepay off ({where}): no service charge line above the Total", st["sc_in_breakdown"], [[], [], []])
        check(f"prepay off ({where}): no '+ $X service charges paid onboard' line under the big total",
              not st["old_note"] and "service charges paid onboard (can be removed" not in st["text"], "")
        check(f"prepay off ({where}): 'Total to pay now'", all(l.startswith("TOTAL TO PAY NOW") or l.startswith("Total to pay now") for l in st["labels"]), st["labels"])
        same(f"prepay off ({where}): '(paid onboard, not in the total)' only on those 4 lines", st["text"].count("(paid onboard, not in the total)"), 4)

    def is_on(st, where):
        check(f"prepay on ({where}): switch checked, title and subtitle", (st["checked"], st["title"], st["desc"]) == (True, ON_TITLE, ON_DESC), (st["checked"], st["title"], st["desc"]))
        same(f"prepay on ({where}): no onboard line, nothing between the Total and the cost per night", (st["onboard"], st["after_total"]), ([[], [], []], [["Cost per night"]] * 3))
        same(f"prepay on ({where}): service charges inside the total, above it (8 nights: in each ship's part)",
             st["sc_in_breakdown"], [[(f"Service charges (crew gratuities): {sc_part('getaway')}", fm(want_onboard[0]))],
                                     [(f"Service charges (crew gratuities): {sc_part('aura')}", fm(want_onboard[1]))],
                                     [(f"Service charges (crew gratuities): {sc_part('getaway')}", fm(want_onboard[0])),
                                      (f"Service charges (crew gratuities): {sc_part('aura')}", fm(want_onboard[1]))]])
        check(f"prepay on ({where}): no line marked onboard", "paid onboard" not in st["text"], "")

    page = new_page(viewport={"width": 360, "height": 800})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{base}/real/index.html")
    page.wait_for_selector(".card .price-total")
    off = state(page)
    is_off(off, "first visit, the default")
    check("no 'Due before you sail' or 'Charged onboard' lines", "Due before you sail" not in off["text"] and "Charged onboard" not in off["text"])
    page.click("#prepayToggle")
    on = state(page)
    is_on(on, "flipped on")
    width = page.evaluate("Math.max(document.documentElement.scrollWidth, document.body.scrollWidth)")
    check("prepay on: no sideways scrolling at 360 px", width <= 360, f"page width {width}")
    check("prepay on: each total = the off total + its service charges",
          [round(a - b, 2) for a, b in zip(on["totals"], off["totals"])] == want_onboard, ([round(a - b, 2) for a, b in zip(on["totals"], off["totals"])], want_onboard))
    page.click("#prepayToggle")
    back = state(page)
    is_off(back, "flipped back off")
    check("flipped back off: same totals as before", back["totals"] == off["totals"], back["totals"])
    width = page.evaluate("Math.max(document.documentElement.scrollWidth, document.body.scrollWidth)")
    check("prepay off: no sideways scrolling at 360 px", width <= 360, f"page width {width}")
    page.click("#prepayToggle")
    page.reload()
    page.wait_for_selector(".card .price-total")
    saved_on = state(page)
    is_on(saved_on, "page load from a saved 'on'")
    check("saved 'on': same totals as flipped on", saved_on["totals"] == on["totals"], saved_on["totals"])
    page.click("#prepayToggle")
    page.reload()
    page.wait_for_selector(".card .price-total")
    is_off(state(page), "page load from a saved 'off'")
    check("prepay switch: no script errors", not errors, errors[:3])
    print(f"      prepay off totals (Getaway, Aura, 8 nights): {off['totals']}; on: {on['totals']}")

    # Choices saved before 5.0.0 (old key, prepay on): guests and kid ages kept, prepay reset to off once.
    page.evaluate("""() => { localStorage.clear();
        localStorage.setItem("cruise-decision-guide-v4", JSON.stringify({ adults: 2, kids: [15, 7], type: "balcony", mode: "same", prepayGratuities: true })); }""")
    page.reload()
    page.wait_for_selector(".card .price-total")
    mig = state(page)
    kid_ages = page.eval_on_selector_all("select[data-kid]", "els => els.map(e => e.value)")
    check("old saved choices: kids and ages kept", kid_ages == ["15", "7"], kid_ages)
    check("old saved choices: prepay reset to off", (mig["checked"], mig["title"]) == (False, OFF_TITLE), (mig["checked"], mig["title"]))
    page.click("#prepayToggle")
    page.reload()
    page.wait_for_selector(".card .price-total")
    check("after the reset, a new 'on' choice is kept", page.is_checked("#prepayToggle"), "")

    # No "Added cost in [cabin]" line (5.0.0), at 4 guests, in both 8 night modes, prepay off and on.
    for mode in ("same", "different"):
        for prepay in (False, True):
            page.evaluate("""s => { localStorage.clear(); localStorage.setItem("cruise-decision-guide-v5", JSON.stringify(s)); }""",
                          {"adults": 2, "kids": [15, 7], "type": "balcony", "mode": mode, "prepayGratuities": prepay})
            page.reload()
            page.wait_for_selector(".card .price-total")
            text = page.inner_text("#app")
            totals = [money(c.query_selector(".price-total").inner_text()) for c in page.query_selector_all(".card")[:3]]
            where = f"4 guests, {mode} cabin, prepay {'on' if prepay else 'off'}"
            check(f"no 'Added cost' line ({where})", "Added cost" not in text and not page.query_selector(".addon"), "")
            check(f"8 night total = Getaway + Aura ({where})", abs(totals[2] - totals[0] - totals[1]) < 0.01, totals)
            width = page.evaluate("Math.max(document.documentElement.scrollWidth, document.body.scrollWidth)")
            check(f"no sideways scrolling at 360 px ({where})", width <= 360, f"page width {width}")
            print(f"      {where}: {totals}")
    check("4 guest checks: no script errors", not errors, errors[:3])
    page.close()

    # Kids Sail Free (5.0.0): informational line under the total, only while NCL lists the offer,
    # judged on the chosen cabin's own prices; never changes a total.
    AGREE = "Kids Sail Free: 3rd and 4th guests sail free. They pay only taxes, fees and port expenses, already in the price above."
    FARE = "NCL lists Kids Sail Free on this sailing, but today's prices charge the 3rd and 4th guests a fare. The total uses NCL's prices."
    AGREE3 = "Kids Sail Free: 3rd guest sails free. This guest pays only taxes, fees and port expenses, already in the price above."
    FARE3 = "NCL lists Kids Sail Free on this sailing, but today's prices charge the 3rd guest a fare. The total uses NCL's prices."
    real_totals = {}
    for name in ("real", "ksf"):
        page = new_page(viewport={"width": 360, "height": 800})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{base}/{name}/index.html")
        page.wait_for_selector(".card .price-total")
        cards = page.query_selector_all(".card")[:3]
        lines = [[n.inner_text() for n in c.query_selector_all(".ksf-note")] for c in cards]
        totals = [c.query_selector(".price-total").inner_text() for c in cards]
        if name == "real":
            real_totals = totals
            check("Kids Sail Free not listed (today's data): no line", lines == [[], [], []], lines)
        else:
            print(f"      Getaway: {lines[0]}\n      Aura: {lines[1]}\n      8 nights: {lines[2]}")
            check("Kids Sail Free, Getaway BF (prices agree): taxes-only wording", lines[0] == [AGREE], lines[0])
            check("Kids Sail Free, Aura BF (holds 2 guests): no line", lines[1] == [], lines[1])
            check("Kids Sail Free line never changes a total (2 adults)", totals == real_totals, (totals, real_totals))
            page.click('button[data-pick="pickA"][data-code="B4"]')
            cards = page.query_selector_all(".card")[:3]
            lines = [[n.inner_text() for n in c.query_selector_all(".ksf-note")] for c in cards]
            print(f"      Aura B4: {lines[1]}\n      8 nights: {lines[2]}")
            check("Kids Sail Free, Aura B4 (prices charge a fare): fare wording", lines[1] == [FARE], lines[1])
            check("Kids Sail Free, 8 night card: one line per ship with its name", lines[2] == ["Kids Sail Free on the Getaway: " + AGREE.removeprefix("Kids Sail Free: "), "Kids Sail Free on the Aura: " + FARE.replace("NCL lists Kids Sail Free on this sailing", "listed by NCL")], lines[2])
            width = page.evaluate("Math.max(document.documentElement.scrollWidth, document.body.scrollWidth)")
            check("Kids Sail Free: no sideways scrolling at 360 px", width <= 360, f"page width {width}")
            page.click('button[data-type="suite"]')
            aura_suite = [n.inner_text() for n in page.query_selector_all(".card")[1].query_selector_all(".ksf-note")]
            check("Kids Sail Free: no line for a cabin type NCL doesn't list (Aura Suite)", aura_suite == [], aura_suite)
            # A cabin that takes 3 guests but not 4 (none on June today, so built here): taxes 100.
            three = page.evaluate("""() => {
                const by = third => ({ "2": { available: true, cabin_total: 1000 }, "3": { available: true, cabin_total: third },
                                       "4": { available: false, reason: "Holds only 3 guests" } });
                const ship = cat => ({ kids_sail_free: { types: ["BALCONY"] }, taxes_per_guest: 100,
                                       types: [{ code: "BALCONY", categories: [cat] }] });
                const strip = h => h.replace(/<[^>]+>/g, "").replace(/&#39;/g, "'");
                const agree = { code: "ZZ", by_guests: by(1101) }, fare = { code: "ZZ", by_guests: by(1250) };
                return [strip(ksfNote(ship(agree), agree)), strip(ksfNote(ship(fare), fare)),
                        strip(ksfNote(ship(agree), agree, "Aura")), strip(ksfNote(ship(fare), fare, "Aura")),
                        strip(ksfNote(ship(fare), fare, "Getaway"))];
            }""")
            print(f"      3 guest cabin: {three}")
            check("Kids Sail Free, cabin for 3 (prices agree): 3rd guest wording", three[0] == AGREE3, three[0])
            check("Kids Sail Free, cabin for 3 (prices charge a fare): 3rd guest wording", three[1] == FARE3, three[1])
            check("Kids Sail Free, cabin for 3 on the 8 night card (prices agree)", three[2] == "Kids Sail Free on the Aura: " + AGREE3.removeprefix("Kids Sail Free: "), three[2])
            check("Kids Sail Free, cabin for 3 on the 8 night card (prices charge a fare)", three[3] == "Kids Sail Free on the Aura: " + FARE3.replace("NCL lists Kids Sail Free on this sailing", "listed by NCL"), three[3])
            check("Kids Sail Free, cabin for 3 on the 8 night card, Getaway (prices charge a fare)", three[4] == "Kids Sail Free on the Getaway: " + FARE3.replace("NCL lists Kids Sail Free on this sailing", "listed by NCL"), three[4])
            check("Kids Sail Free, 8 night lines are trimmed (offer name once)", all(t.count("Kids Sail Free") == 1 for t in three[2:]), three[2:])
            if SHOTS:
                page.click('button[data-type="balcony"]')
                page.click('button[data-pick="pickA"][data-code="B4"]')
                page.query_selector_all(".card")[0].screenshot(path=os.path.join(SHOTS, "ksf_getaway.png"))
                page.query_selector_all(".card")[1].screenshot(path=os.path.join(SHOTS, "ksf_aura.png"))
        check(f"Kids Sail Free ({name}): no script errors", not errors, errors[:3])
        page.close()

    # Florida resident rate (5.1.0): switch on by default, in the gratuities card. The page works
    # out from data/florida.json whether NCL offers a discount; each cabin's own amount comes off
    # the fare of guests 1 and 2; switched off, website prices and nothing extra.

    def fl_open(name, stored=None):
        page = new_page(viewport={"width": 360, "height": 800})
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.on("console", lambda m: errs.append(m.text) if console_error(m) else None)
        page.goto(f"{base}/{name}/index.html")
        page.evaluate("s => { localStorage.clear(); if (s) localStorage.setItem('cruise-decision-guide-v5', JSON.stringify(s)); }", stored)
        page.reload()
        page.wait_for_selector(".card .price-total")
        return page, errs

    def fl_state(page):
        cards = page.query_selector_all(".card")[:3]
        desc = page.query_selector("#flDesc")
        pill = page.query_selector("#flAsOf")
        return {"checked": page.is_checked("#flToggle"), "label": page.inner_text("#flLabel"),
                "title": page.inner_text("section[aria-label='Florida resident rate and gratuities'] .panel-title"),
                "desc": desc.inner_text() if desc.is_visible() else None,
                "pill": " ".join(page.inner_text("#flAsOf").split()) if pill.is_visible() else None,
                "amber": "old" in (pill.get_attribute("class") or ""),
                "totals": [money(c.query_selector(".price-total").inner_text()) for c in cards],
                "rows": [[(k, v) for k, v in rows_of(c) if k.startswith("Florida")] for c in cards],
                "width": page.evaluate("Math.max(document.documentElement.scrollWidth, document.body.scrollWidth)")}

    page, errs = fl_open("real")
    base_st = fl_state(page)
    page.click('button[data-pick="pickA"][data-code="B4"]')
    base_b4 = fl_state(page)["totals"]
    page.close()
    same("Florida, no file: switch on by default, in the 'Florida resident rate and gratuities' card",
          (base_st["checked"], base_st["label"], base_st["title"].upper()), (True, "Florida resident rate", "FLORIDA RESIDENT RATE AND GRATUITIES"))
    same("Florida, no file: website prices shown, says so", base_st["desc"], "Florida resident prices aren't available right now, so NCL's website prices are shown.")
    same("Florida, no file: no 'Florida rates as of' and no Florida lines", (base_st["pill"], base_st["rows"]), (None, [[], [], []]))
    check("Florida, no file: no script errors", not errs, errs[:3])

    for name, when in FL_SITES_WHEN.items():
        page, errs = fl_open(name)
        st = fl_state(page)
        where = f"Florida {name}"
        if name in ("none", "higher", "old"):
            same(f"{where}: 'Selected' message with the check date", st["desc"], f"Selected. NCL isn't offering a Florida resident discount on these sailings right now (checked {when}).")
            same(f"{where}: totals are website prices", st["totals"], base_st["totals"])
            same(f"{where}: no Florida lines in the cards", st["rows"], [[], [], []])
            same(f"{where}: 'Florida rates as of {when}'", st["pill"], f"Florida rates as of {when}")
            same(f"{where}: date amber only after 9 days", st["amber"], name == "old")
        elif name == "stale":
            same(f"{where} (16 days): not used, says when it was last checked", st["desc"], f"Florida resident prices haven't been checked since {when}, so NCL's website prices are shown.")
            same(f"{where}: no 'Florida rates as of', website totals", (st["pill"], st["totals"]), (None, base_st["totals"]))
        elif name == "both":
            same(f"{where}: discount text", st["desc"], f"NCL's Florida resident prices, checked {when}. The discount comes off the fare for guests 1 and 2 and varies by cabin. Cabins not checked show the website price. Confirm with NCL.")
            same(f"{where}: Getaway BF $60 off for 2 guests, Aura BF no discount",
                  st["rows"][:2], [[(f"Florida resident rate (checked {when.rsplit(',', 1)[0]}): 2 guests x $60 off the fare", "−$120")],
                                   [(f"Florida resident rate (checked {when.rsplit(',', 1)[0]}): no discount for this cabin", "$0")]])
            same(f"{where}: Getaway total $120 lower, Aura the same, 8 nights $120 lower",
                  [round(a - b, 2) for a, b in zip(st["totals"], base_st["totals"])], [-120, 0, -120])
            same(f"{where}: 8 night card shows each ship's line", st["rows"][2], st["rows"][0] + st["rows"][1])
            page.click('button[data-pick="pickA"][data-code="B4"]')
            st2 = fl_state(page)
            same(f"{where}: Aura B4 uses its own amount ($25 x 2)", [round(a - b, 2) for a, b in zip(st2["totals"], base_b4)], [-120, -50, -170])
            page.click('button[data-pick="pickG"][data-code="B4"]')
            gb4 = fl_state(page)["rows"][0]
            same(f"{where}: a cabin the check didn't cover says so", gb4, [("Florida resident rate: not checked for this cabin", "no discount")])
            page.click("#flToggle")
            off = fl_state(page)
            same(f"{where}: switched off: website totals, no Florida lines, nothing under the switch",
                  (off["checked"], off["rows"], off["desc"]), (False, [[], [], []], None))
            page.reload()
            page.wait_for_selector(".card .price-total")
            same(f"{where}: 'off' is kept on reload", page.is_checked("#flToggle"), False)
            # 4 guests (2 adults, kids 15 and 7): the discount is for guests 1 and 2 only.
            page4, errs4 = fl_open(name, {"adults": 2, "kids": [15, 7], "type": "balcony", "mode": "same"})
            four = fl_state(page4)
            errs += errs4
            same(f"{where}, 4 guests: still 2 guests x $60 on the Getaway", four["rows"][0][:1], [(f"Florida resident rate (checked {when.rsplit(',', 1)[0]}): 2 guests x $60 off the fare", "−$120")])
            check(f"{where}, 4 guests: 8 night total = Getaway + Aura", abs(four["totals"][2] - four["totals"][0] - four["totals"][1]) < 0.01, four["totals"])
            check(f"{where}, 4 guests: no sideways scrolling at 360 px", four["width"] <= 360, four["width"])
            if SHOTS:
                page4.query_selector("section[aria-label='Florida resident rate and gratuities']").screenshot(path=os.path.join(SHOTS, "florida_switch.png"))
                page4.query_selector_all(".card")[0].screenshot(path=os.path.join(SHOTS, "florida_getaway_4.png"))
                page4.query_selector_all(".card")[2].screenshot(path=os.path.join(SHOTS, "florida_8_nights_4.png"))
            page4.close()
        elif name == "one":
            same(f"{where}: discount on the Getaway only, names both ships", st["desc"],
                  f"NCL's Florida resident prices on the Getaway, checked {when}. The discount comes off the fare for guests 1 and 2 and varies by cabin. Cabins not checked show the website price. The Aura has no Florida resident discount right now. Confirm with NCL.")
            same(f"{where}: no Florida line on the Aura card", st["rows"][1], [])
        check(f"{where}: no sideways scrolling at 360 px", st["width"] <= 360, st["width"])
        check(f"{where}: no script errors", not errs, errs[:3])
        if SHOTS and name in ("none", "old"):
            page.screenshot(path=os.path.join(SHOTS, f"florida_{name}_360.png"))
        page.close()

    # Make Selection (5.2.0): the booking request window.
    today_e = dt.datetime.now(MIAMI).date()

    def offers_file(listed=True, read_days_ago=0, types=("BALCONY", "MINISUITE", "SUITE", "HAVEN"), min_days=90):
        on = (today_e - dt.timedelta(days=read_days_ago)).isoformat()
        return {"schema_version": 1, "saved_at": f"{on}T12:00:00Z", "checked_on": on, "source": "https://www.ncl.com/cruise-deals/cruisenext",
                "read_ok": True, "warnings": [],
                "doubleup": {"listed": listed, "title": "Limited-Time Offer: DoubleUp!" if listed else None,
                             "text": "Book a Balcony and above stateroom on any sailing at least 90 days prior to sailing and apply TWO CruiseNext credits." if listed else None,
                             "types": list(types) if listed else None, "min_days": min_days if listed else None, "min_months": None,
                             "read_on": on, "since": on},
                "last_change": None}

    # A stand-in for Cloudflare Turnstile: Cloudflare's own script is never loaded in the test.
    TURNSTILE_STUB = ("window.turnstile = { render: (el, o) => { setTimeout(() => o.callback('test-token'), 0); return 'w1'; },"
                      " remove() {}, reset() {} };")

    def ms_open(site, stored=None, offers=None, ready=".card .price-total"):
        page = new_page(viewport={"width": 360, "height": 800})
        errs, sent = [], []
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.on("console", lambda m: errs.append(m.text) if console_error(m) else None)
        if offers is not None:
            page.route("**/data/offers.json", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(offers)))
        page.route("https://challenges.cloudflare.com/**", lambda r: r.abort())
        page.add_init_script(TURNSTILE_STUB)

        def worker(route):
            sent.append(json.loads(route.request.post_data))
            route.fulfill(status=200, content_type="application/json", body='{"ok": true}', headers={"Access-Control-Allow-Origin": "*"})
        page.route(FAMILY_API_TEST + "/booking", worker)
        page.goto(f"{base}/{site}/index.html")
        page.evaluate("s => { localStorage.clear(); if (s) localStorage.setItem('cruise-decision-guide-v5', JSON.stringify(s)); }", stored)
        page.reload()
        page.wait_for_selector(ready)
        return page, errs, sent

    def wide(page):
        return page.evaluate("Math.max(document.documentElement.scrollWidth, document.body.scrollWidth)")

    def dialog_fits(page):
        return page.evaluate("(() => { const d = document.getElementById('msDialog'); return d.scrollWidth <= d.clientWidth; })()")

    def booking_rows(page, key):
        box = page.query_selector(f"#msMath [data-booking='{key}']")
        return [(r.query_selector(".k").inner_text(), r.query_selector(".v").inner_text()) for r in box.query_selector_all(".row")]

    def choice_texts(page, key):
        return [l.inner_text() for l in page.query_selector_all(f"#msMath [data-booking='{key}'] .ms-choice")]

    def sail_dob(age, adult=False):
        """A date of birth that makes the guest `age` on Jun 11, 2027 (30 days past the birthday)."""
        return (dt.date(2027 - age, 6, 11) - dt.timedelta(days=30)).isoformat()

    def fill_guests(page, ages):
        for i, a in enumerate(ages):
            page.fill(f"#g{i}_first", f"Test{i + 1}")
            page.fill(f"#g{i}_last", "Guest")
            page.fill(f"#g{i}_dob", sail_dob(40) if a is None else sail_dob(a))
            page.select_option(f"#g{i}_gender", "Female")
            page.fill(f"#g{i}_citizenship", "United States")
        page.fill("#g0_email", "guest1@example.com")
        page.fill("#g0_phone", "305 555 0100")

    gw = next(x for x in sites["ms_api"]["sailings"] if x["id"].startswith("getaway"))
    au = next(x for x in sites["ms_api"]["sailings"] if x["id"].startswith("aura"))
    cat = lambda sl, code: next(c for t in sl["types"] for c in t["categories"] if c["code"] == code)
    doubleup_on = offers_file()

    # 1. Getaway card, 2 adults, Balcony (default BF). DoubleUp on today.
    page, errs, _ = ms_open("ms_api", offers=doubleup_on)
    same("Make Selection: a button on each card", page.eval_on_selector_all("button[data-select]", "els => els.map(e => e.dataset.select)"), ["G", "A", "8"])
    page.click('button[data-select="G"]')
    check("Make Selection: the window opens", page.is_visible("#msDialog"))
    same("Make Selection: 'Prices can change until NCL confirms the booking' in the window",
         page.inner_text("#msDialog").count("Prices can change until NCL confirms the booking."), 2)
    same("Make Selection: no price until the Florida question is answered",
         page.inner_text("#msMath").splitlines()[-1], "Answer the Florida question above to see the price, the deposit and the balance.")
    same("Make Selection: Florida question starts with nothing selected",
         page.eval_on_selector_all("input[name='msFl']", "els => els.filter(e => e.checked).length"), 0)
    page.check("input[name='msFl'][value='no']")
    rows = booking_rows(page, "G")
    bf = cat(gw, "BF")["by_guests"]["2"]
    fare, taxes = bf["cabin_total"] - 2 * gw["taxes_per_guest"], 2 * gw["taxes_per_guest"]
    same("Make Selection: price without gratuities = fare + taxes", [r for r in rows[:3]],
         [("Cruise fare", f"${fare:,}"), (f"Taxes, fees and port expenses: 2 x ${gw['taxes_per_guest']:g}", f"${taxes:,}"), ("Price without gratuities", f"${bf['cabin_total']:,}")])
    labels = [k for k, v in rows]
    check("Make Selection: gratuities listed below the price, not added",
          any(k.startswith("Unlimited Open Bar") for k in labels) and any(k.startswith("Service charges") for k in labels), labels)
    texts = choice_texts(page, "G")
    same("Make Selection: NCL's deposit with the 2-For-1 line, one credit, two credits (DoubleUp, Balcony)", [t.split("\n")[0] for t in texts],
         ["NCL's deposit: $100 ($50 per guest x 2), due within 76 hours of booking", "One of David's CruiseNext credits: $250 toward the cruise, you pay David $125",
          "Two of David's CruiseNext credits (NCL's DoubleUp offer): $500 toward the cruise, you pay David $250"])
    check("Make Selection: NCL's deposit offer in NCL's words", "Includes NCL's 2-For-1 Deposits offer: Lock-in this vacation today" in texts[0], texts[0])
    check("Make Selection: CruiseNext steps hidden until a credit is chosen", not page.is_visible("#msCn"))
    page.check("input[name='msDepG'][value='ncl']")
    rows = booking_rows(page, "G")
    same("Make Selection, NCL deposit: deposit and balance by the final payment date", rows[-2:],
         [("Deposit to NCL at booking", "$100"), ("Balance, due by Feb 11, 2027", f"${bf['cabin_total'] - 100:,}")])
    page.check("input[name='msDepG'][value='credit1']")
    rows = booking_rows(page, "G")
    same("Make Selection, one credit: $250 off, no deposit due, pay David $125", rows[-4:],
         [("CruiseNext credit toward the cruise: 1 x $250", "−$250"), ("Deposit due at booking (the credit is the deposit)", "$0"),
          ("Balance, due by Feb 11, 2027", f"${bf['cabin_total'] - 250:,}"), ("Pay David for the credits", "$125")])
    check("Make Selection, credit: CruiseNext steps shown with NCL's sign-up page",
          page.is_visible("#msCn") and page.get_attribute("#msCn a", "href") == "https://www.ncl.com/account-access/register")
    same("Make Selection, credit: Latitudes number required", page.inner_text("#msLatNeed"), "(required for CruiseNext)")
    early = today_e < dt.date(2026, 11, 26)
    same("Make Selection, credit: 'can't be completed before about Nov 26, 2026' only before that date",
         "can't be completed before about Nov 26, 2026" in page.inner_text("#msCn"), early)
    page.check("input[name='msDepG'][value='credit2']")
    rows = booking_rows(page, "G")
    same("Make Selection, two credits: $500 off, pay David $250", [rows[-4], rows[-1]], [("CruiseNext credits toward the cruise: 2 x $250", "−$500"), ("Pay David for the credits", "$250")])
    check("Make Selection, two credits: note about DoubleUp ending", page.is_visible("#msTwoNote"))
    page.click("#msSend")
    st = page.inner_text("#msStatus")
    check("Make Selection: sending an empty form lists what's missing", "Enter guest 1's first name." in st and "Enter guest 1's Latitudes number" in st, st[:200])
    check("Make Selection: no sideways scrolling at 360 px", wide(page) <= 360 and dialog_fits(page), wide(page))
    page.click("[data-ms-close]")
    page.wait_for_function("document.getElementById('msDialog').innerHTML === ''", timeout=3000)
    check("Make Selection: closing clears the window", not page.is_visible("#msDialog") and page.inner_html("#msDialog") == "")
    check("Make Selection: no script errors", not errs, errs[:3])
    page.close()

    # 2. DoubleUp: read too long ago, ended, or not covering the cabin: one credit only.
    for name, offers, stored in [("read 4 days ago", offers_file(read_days_ago=4), None), ("ended", offers_file(listed=False), None),
                                 ("Inside cabin", doubleup_on, {"adults": 2, "kids": [], "type": "inside", "mode": "same"}),
                                 ("no offers file", None, None)]:
        page, errs, _ = ms_open("ms_api" if offers is not None else "real", stored=stored, offers=offers)
        page.click('button[data-select="G"]')
        page.check("input[name='msFl'][value='no']")
        same(f"Make Selection, DoubleUp {name}: one credit only", len(choice_texts(page, "G")), 2)
        check(f"Make Selection, DoubleUp {name}: no script errors", not errs, errs[:3])
        page.close()

    # 3. Haven on the Aura: NCL's 10% rule, a credit covers part of the deposit.
    page, errs, _ = ms_open("ms_api", stored={"adults": 2, "kids": [], "type": "haven", "mode": "same"}, offers=doubleup_on)
    page.click('button[data-select="A"]')
    page.check("input[name='msFl'][value='no']")
    head = page.inner_text("#msMath [data-booking='A'] .cabin-line")
    code = head.rsplit("(", 1)[1].rstrip(")")
    hv = cat(au, code)["by_guests"]["2"]
    dep = round((hv["cabin_total"] - 2 * au["taxes_per_guest"]) * 0.10, 2)
    dep_text = f"${dep:,.2f}".replace(".00", "")
    texts = choice_texts(page, "A")
    check(f"Make Selection, Haven {code}: NCL's deposit is 10% of the cruise fare ({dep_text})",
          texts[0].startswith(f"NCL's deposit: {dep_text} (10% of the cruise fare, NCL's rule for Suites and The Haven)"), texts[0])
    check("Make Selection, Haven: no 2-For-1 line", "2-For-1" not in texts[0], texts[0])
    check("Make Selection, Haven: says a credit covers part of the deposit", "covers part of NCL's deposit" in texts[1], texts[1])
    page.check("input[name='msDepA'][value='credit1']")
    rows = booking_rows(page, "A")
    rest = round(dep - 250, 2)
    same("Make Selection, Haven, one credit: the rest of NCL's deposit is due at booking", rows[-3][0], "Rest of NCL's deposit, due at booking")
    check("Make Selection, Haven, one credit: rest = deposit - $250, balance = price - $250 - rest",
          abs(money(rows[-3][1]) - rest) < 0.01 and abs(money(rows[-2][1]) - (hv["cabin_total"] - 250 - rest)) < 0.01, rows[-3:])
    check("Make Selection, Haven: no script errors", not errs, errs[:3])
    page.close()

    # 4. Florida answer overrides the page switch (Getaway BF $60 off per guest in the "both" file).
    page, errs, _ = ms_open("both")
    page.click('button[data-select="G"]')
    page.check("input[name='msFl'][value='no']")
    same("Make Selection, Florida No with the switch on: says so", page.inner_text("#msFlNote"),
         "The Florida resident rate switch on the page is on. Your answer turns the Florida resident rate off for this request.")
    no_price = money(dict(booking_rows(page, "G"))["Price without gratuities"])
    check("Make Selection, Florida No: no address fields", not page.is_visible("#msAddr"))
    page.check("input[name='msFl'][value='yes']")
    rows = dict(booking_rows(page, "G"))
    same("Make Selection, Florida Yes: $60 x 2 off, price $120 lower",
         (rows.get("Florida resident rate: 2 guests x $60 off the fare"), no_price - money(rows["Price without gratuities"])), ("−$120", 120))
    check("Make Selection, Florida Yes: guest 1's Florida home address asked", page.is_visible("#msAddr") and page.input_value("#msState") == "FL")
    check("Make Selection, Florida Yes with the switch on: no note", not page.is_visible("#msFlNote"))
    page.click("[data-ms-close]")
    page.click("#flToggle")
    page.click('button[data-select="G"]')
    page.check("input[name='msFl'][value='yes']")
    same("Make Selection, Florida Yes with the switch off: says so", page.inner_text("#msFlNote"),
         "The Florida resident rate switch on the page is off. Your answer turns the Florida resident rate on for this request.")
    check("Make Selection, Florida Yes with the switch off: discount applied", "Florida resident rate: 2 guests x $60 off the fare" in dict(booking_rows(page, "G")))
    check("Make Selection, Florida: no script errors", not errs, errs[:3])
    page.close()
    page, errs, _ = ms_open("none")
    page.click('button[data-select="G"]')
    page.check("input[name='msFl'][value='yes']")
    same("Make Selection, Florida Yes with no discount offered: says the price is the same", page.inner_text("#msFlNote"),
         "NCL isn't offering a Florida resident discount on this selection right now, so the price is the same either way.")
    page.close()

    # 5. 8 nights: two bookings and the totals, 4 guests (2 adults, kids 15 and 7).
    page, errs, _ = ms_open("ms_api", stored={"adults": 2, "kids": [15, 7], "type": "balcony", "mode": "same"}, offers=doubleup_on)
    page.click('button[data-select="8"]')
    page.check("input[name='msFl'][value='no']")
    check("Make Selection, 8 nights: totals wait for both deposit choices", "Choose how to pay each deposit" in page.inner_text("#msMath"))
    page.check("input[name='msDepG'][value='credit1']")
    page.check("input[name='msDepA'][value='ncl']")
    g_rows, a_rows = dict(booking_rows(page, "G")), dict(booking_rows(page, "A"))
    same("Make Selection, 8 nights, 4 guests: NCL's deposit $200 on the Aura", a_rows["Deposit to NCL at booking"], "$200")
    tot = page.query_selector_all("#msMath .ms-booking")[-1]
    trows = dict((r.query_selector(".k").inner_text(), r.query_selector(".v").inner_text()) for r in tot.query_selector_all(".row"))
    same("Make Selection, 8 nights: price = both prices", money(trows["Price without gratuities"]),
         money(g_rows["Price without gratuities"]) + money(a_rows["Price without gratuities"]))
    same("Make Selection, 8 nights: balances listed with each date and added",
         money(trows["Balances: Getaway due by Feb 11, 2027, Aura due by Feb 14, 2027"]),
         money(g_rows["Balance, due by Feb 11, 2027"]) + money(a_rows["Balance, due by Feb 14, 2027"]))
    same("Make Selection, 8 nights: pay David $125, at booking $200", (trows["Pay David for the credits"], trows["Paid to NCL at booking"]), ("$125", "$200"))
    same("Make Selection, 4 guests: guest details in NCL's order",
         [l.inner_text() for l in page.query_selector_all(".ms-guest legend")], ["Guest 1 (adult)", "Guest 2 (adult)", "Guest 3 (age 15 on Jun 11, 2027)", "Guest 4 (age 7 on Jun 11, 2027)"])
    fill_guests(page, [None, None, 15, 7])
    page.fill("#g3_dob", sail_dob(8))
    page.check("#msMe")
    page.fill("#g0_latitudes", "123456789")
    page.click("#msSend")
    st = page.inner_text("#msStatus")
    same("Make Selection: a kid's date of birth must match the age on the page", "Guest 4's date of birth makes them 8 on Jun 11, 2027, but the page says 7." in st, True)
    page.fill("#g3_dob", sail_dob(7))
    page.click("#msSend")
    page.wait_for_selector(".ms-status.ok")
    check("Make Selection, 8 nights: no sideways scrolling at 360 px", wide(page) <= 360, wide(page))
    page.close()

    # 6. Sending to the stand-in Worker: the request, Turnstile's token, nothing saved in the browser.
    page, errs, sent = ms_open("ms_api", stored={"adults": 2, "kids": [15], "type": "balcony", "mode": "same"}, offers=doubleup_on)
    page.click('button[data-select="G"]')
    page.check("input[name='msFl'][value='yes']")
    page.check("input[name='msDepG'][value='credit1']")
    fill_guests(page, [None, None, 15])
    page.fill("#g0_latitudes", "123456789")
    page.fill("#msStreet", "1 Test Street")
    page.fill("#msCity", "Miami")
    page.fill("#msZip", "33101")
    page.fill("#msName", "Test Sender")
    page.fill("#msEmail", "sender@example.com")
    page.click("#msSend")
    page.wait_for_selector(".ms-status.ok")
    same("Make Selection, send: one request to the Worker", len(sent), 1)
    req = sent[0] if sent else {}
    b0 = (req.get("bookings") or [{}])[0]
    same("Make Selection, send: the request", (req.get("kind"), req.get("turnstile"), req.get("option"), req.get("note"), req.get("party")),
         ("booking", "test-token", "Option 1: 3 nights", "Prices can change until NCL confirms the booking.", {"adults": 2, "kid_ages": [15]}))
    same("Make Selection, send: the booking's numbers", (b0.get("ship"), b0.get("deposit_choice"), b0.get("credits"), b0.get("due_at_booking"), b0.get("pay_david"), b0.get("balance_due")),
         ("Norwegian Getaway", "credit1", 1, 0, 125, "2027-02-11"))
    same("Make Selection, send: price - credit = balance", b0.get("price_without_gratuities", 0) - 250, b0.get("balance"))
    same("Make Selection, send: guests and the Florida address",
         ([g["first"] for g in req.get("guests", [])], req.get("florida")),
         (["Test1", "Test2", "Test3"], {"residents": True, "address": {"street": "1 Test Street", "city": "Miami", "state": "FL", "zip": "33101"}}))
    same("Make Selection, send: sender", req.get("sender"), {"is_guest1": False, "name": "Test Sender", "email": "sender@example.com"})
    stored = page.evaluate("JSON.stringify(Object.assign({}, localStorage))")
    check("Make Selection, send: nothing typed is saved in the browser", not any(x in stored for x in ("Test1", "Test Street", "123456789", "sender@example.com")), stored[:200])
    check("Make Selection, send: no sideways scrolling at 360 px", wide(page) <= 360, wide(page))
    check("Make Selection, send: no script errors", not errs, errs[:3])
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "make_selection_sent.png"))
    page.close()

    # 7. Without the Worker's address (until part B): checks run, nothing is sent.
    page, errs, _ = ms_open("real")
    page.click('button[data-select="A"]')
    page.check("input[name='msFl'][value='no']")
    page.check("input[name='msDepA'][value='ncl']")
    fill_guests(page, [None, None])
    page.check("#msMe")
    page.click("#msSend")
    same("Make Selection, no Worker yet: says nothing was sent", page.inner_text("#msStatus"),
         "Everything is filled in. Sending isn't switched on yet: the email service is set up in the next part of this update. Nothing was sent.")
    page.close()

    # 8. A schema 3 price file (no payment data): the deposit is never guessed.
    page, errs, _ = ms_open("schema3")
    page.click('button[data-select="G"]')
    page.check("input[name='msFl'][value='no']")
    same("Make Selection, schema 3 file: NCL's deposit not found, David will confirm", choice_texts(page, "G")[0],
         "NCL's deposit (not found on NCL today; David will confirm it)")
    page.check("input[name='msDepG'][value='ncl']")
    same("Make Selection, schema 3 file: balance left to David", booking_rows(page, "G")[-1], ("Balance, due by NCL's final payment date (not found on NCL today)", "David will confirm"))
    check("Make Selection, schema 3 file: no script errors", not errs, errs[:3])
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "make_selection_schema3.png"))
    page.close()

    # 9. A kid without an age: no Make Selection button.
    page, errs, _ = ms_open("ms_api", stored={"adults": 2, "kids": [None], "type": "balcony", "mode": "same"}, ready=".card .rows")
    same("Make Selection: no button until every kid's age is chosen", page.eval_on_selector_all("button[data-select]", "els => els.length"), 0)
    page.close()


    # Option tiles (5.2.0): three on/off tiles, none selected on the first visit, the full card of
    # each selected option below them in tile order, remembered on the device. 360 px and wide.
    def ys(page, sel):
        return [round(b["y"]) for b in page.eval_on_selector_all(sel, "els => els.map(e => e.getBoundingClientRect().toJSON())")]

    def xs(page, sel):
        return [round(b["x"]) for b in page.eval_on_selector_all(sel, "els => els.map(e => e.getBoundingClientRect().toJSON())")]

    def tiles_state(page):
        return {"pressed": page.eval_on_selector_all(".tile-btn", "els => els.map(e => e.getAttribute('aria-pressed'))"),
                "on": page.eval_on_selector_all(".tile", "els => els.map(e => e.classList.contains('on'))"),
                "words": page.eval_on_selector_all(".tile-state", "els => els.map(e => e.lastChild.textContent.trim())"),
                "cards": page.eval_on_selector_all(".card", "els => els.map(e => e.dataset.option)"),
                "prompt": page.inner_text(".tiles-prompt") if page.query_selector(".tiles-prompt") else None,
                "width": wide(page)}

    PROMPT = "Pick one or more options to compare."
    for w in (360, 1280):
        page = new_page({"width": w, "height": 900}, tiles=False)
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.on("console", lambda m: errs.append(m.text) if console_error(m) else None)
        page.goto(f"{base}/real/index.html")
        page.wait_for_selector(".tile")
        st = tiles_state(page)
        where = f"tiles at {w} px"
        same(f"{where}: first visit, no tile selected", (st["pressed"], st["on"], st["words"]), (["false"] * 3, [False] * 3, ["Tap to compare"] * 3))
        same(f"{where}: first visit, the prompt under the tiles and no cards", (st["prompt"], st["cards"]), (PROMPT, []))
        check(f"{where}: first visit, no sideways scrolling", st["width"] <= w, st["width"])
        tile_text = page.eval_on_selector_all(".tile", "els => els.map(e => e.innerText)")
        check(f"{where}: each tile has its label, ship, dates and nights",
              all(all(x in t for x in want) for t, want in zip(tile_text, [("OPTION 1: 3 NIGHTS", "Norwegian Getaway", "Jun 11 to", "(3 nights)", "Nassau"),
                                                                           ("OPTION 2: 5 NIGHTS", "Norwegian Aura", "Jun 14 to", "(5 nights)", "Puerto Plata"),
                                                                           ("OPTION 3: 8 NIGHTS", "Getaway, then Aura", "Jun 11 to", "(8 nights)", "Change ships in Miami")])), tile_text)
        same(f"{where}: maiden voyage badge, christening note and video link on the Aura tiles only",
             [page.eval_on_selector(f'[data-tile="{k}"]', "e => [!!e.querySelector('.maiden-badge'), !!e.querySelector('.maiden-text'), !!e.querySelector('a.maiden-link')]") for k in "GA8"],
             [[False] * 3, [True] * 3, [True] * 3])
        tops = ys(page, ".tile")
        if w == 360:
            check(f"{where}: tiles stacked", tops[0] < tops[1] < tops[2] and len(set(xs(page, ".tile"))) == 1, tops)
        else:
            check(f"{where}: tiles in one row", len(set(tops)) == 1, tops)
        order = [ys(page, s)[0] for s in ("section[aria-label='Who is in the cabin']", "section[aria-label='Cabin type']",
                                          "section[aria-label='Florida resident rate and gratuities']", ".tiles-wrap")]
        check(f"{where}: page order: who, cabin type, Florida and gratuities, then the tiles", order == sorted(order), order)

        page.click('[data-tile="8"] .tile-title')
        page.click('[data-tile="G"] .tile-btn')
        st = tiles_state(page)
        same(f"{where}: two tiles selected (8 nights first): shown selected, cards in tile order, no prompt",
             (st["pressed"], st["on"], st["words"], st["cards"], st["prompt"]),
             (["true", "false", "true"], [True, False, True], ["Selected", "Tap to compare", "Selected"], ["G", "8"], None))
        cards_y = ys(page, ".card")
        check(f"{where}: selected cards below the tiles", min(cards_y) > max(ys(page, ".tile")), (cards_y, ys(page, ".tile")))
        if w == 360:
            check(f"{where}: two cards stacked", cards_y[0] < cards_y[1] and len(set(xs(page, ".card"))) == 1, cards_y)
        else:
            check(f"{where}: two cards side by side", len(set(cards_y)) == 1 and xs(page, ".card")[0] < xs(page, ".card")[1], cards_y)
        check(f"{where}: two cards, no sideways scrolling", st["width"] <= w, st["width"])
        card8 = page.query_selector('.card[data-option="8"]')
        same(f"{where}: the 8 night card keeps its same or different toggle, both ship pickers and Day by day",
             (len(card8.query_selector_all("button[data-mode]")), len(card8.query_selector_all(".cat-list")), len(card8.query_selector_all("details.days")),
              len(card8.query_selector_all("button[data-select]")), len(card8.query_selector_all("input[data-offer]"))), (2, 2, 2, 1, 6))
        cardg = page.query_selector('.card[data-option="G"]')
        same(f"{where}: the Getaway card has its switches, cabin list, total, Make Selection and Day by day",
             (len(cardg.query_selector_all("input[data-offer]")) == 3, bool(cardg.query_selector(".cat-list")), bool(cardg.query_selector(".price-total")),
              bool(cardg.query_selector("button[data-select]")), bool(cardg.query_selector("details.days"))), (True,) * 5)
        # The video link opens NCL's video and never turns the tile on or off.
        page.eval_on_selector('[data-tile="A"] a.maiden-link', "a => a.addEventListener('click', e => e.preventDefault(), { once: true })")
        page.click('[data-tile="A"] a.maiden-link')
        same(f"{where}: the video link doesn't toggle the tile", tiles_state(page)["pressed"], ["true", "false", "true"])
        page.reload()
        page.wait_for_selector(".card")
        st = tiles_state(page)
        same(f"{where}: return visit shows the tiles picked last", (st["pressed"], st["cards"]), (["true", "false", "true"], ["G", "8"]))
        same(f"{where}: saved with the other choices", page.evaluate("JSON.parse(localStorage.getItem('cruise-decision-guide-v5')).compare"), ["G", "8"])
        page.click('[data-tile="A"] .tile-dates')
        st = tiles_state(page)
        same(f"{where}: all three selected, in tile order", st["cards"], ["G", "A", "8"])
        cards_y = ys(page, ".card")
        if w == 360:
            check(f"{where}: three cards stacked", cards_y == sorted(cards_y) and len(set(cards_y)) == 3, cards_y)
        else:
            check(f"{where}: three cards side by side", len(set(cards_y)) == 1, cards_y)
        check(f"{where}: three cards, no sideways scrolling", st["width"] <= w, st["width"])
        if SHOTS:
            page.screenshot(path=os.path.join(SHOTS, f"tiles_three_{w}.png"), full_page=True)
        page.focus('[data-tile="G"] .tile-btn')
        page.keyboard.press("Enter")
        st = tiles_state(page)
        same(f"{where}: keyboard: Enter on a tile turns it off and keeps the focus there",
             (st["cards"], page.evaluate("document.activeElement.closest('[data-tile]') && document.activeElement.closest('[data-tile]').dataset.tile")), (["A", "8"], "G"))
        page.reload()
        page.wait_for_selector(".card")
        same(f"{where}: a tile turned off stays off on return", tiles_state(page)["cards"], ["A", "8"])
        page.click('[data-tile="A"] .tile-btn')
        page.click('[data-tile="8"] .tile-btn')
        st = tiles_state(page)
        same(f"{where}: none selected again: the prompt is back", (st["cards"], st["prompt"]), ([], PROMPT))
        page.reload()
        page.wait_for_selector(".tile")
        same(f"{where}: none selected is remembered too", (tiles_state(page)["cards"], tiles_state(page)["prompt"]), ([], PROMPT))
        check(f"{where}: no script errors", not errs, errs[:3])
        page.close()

    # Cabin list prices (5.2.0): every price in every list (each card's list, both 8 night pickers
    # in both modes, the full tables) is the cabin total with the current choices and equals the
    # card's Total once that cabin is chosen. Every switch combination, with a Florida discount on
    # some cabins (the "both" test file) and several parties.
    LIST_CHECK = """cfg => {
        Object.assign(state, cfg, { compare: ["G", "A", "8"] });
        render();
        const num = t => Number(String(t).replace(/[^\\d.]/g, ""));
        const card = k => document.querySelector(`.card[data-option="${k}"]`);
        const total = k => num(card(k).querySelector(".price-total").textContent);
        const shipLine = ship => num([...card("8").querySelectorAll(".rows .row")].find(r => r.querySelector(".k").textContent.startsWith(ship + " total")).querySelector(".v").textContent);
        const out = [], order = [];
        const seen = (where, code, shown, got) => out.push([where, code, shown, got]);
        const sorted = () => document.querySelectorAll(".cat-list").forEach(l => {
            const p = [...l.querySelectorAll(".price")].map(x => num(x.textContent));
            if (p.some((x, i) => i && x < p[i - 1])) order.push(p);
        });
        sorted();
        for (const k of ["G", "A", "8"]) {
            const only = card(k).querySelectorAll(".cat-list button.only");
            only.forEach(b => seen(k, "only", num(b.querySelector(".price").textContent), total(k)));
            const picks = [...card(k).querySelectorAll(".cat-list button[data-pick]")].map(b => [b.dataset.pick, b.dataset.code]);
            for (const [f, code] of picks) {
                const b = card(k).querySelector(`button[data-pick="${f}"][data-code="${code}"]`);
                const shown = num(b.querySelector(".price").textContent);
                b.click();
                seen(k + " list", f + " " + code, shown, total(k));
                sorted();
            }
            for (const field of ["diffG", "diffA"]) {
                const sel = () => card(k).querySelector(`select[data-field="${field}"]`);
                if (!sel()) continue;
                for (const v of [...sel().options].map(o => o.value)) {
                    const o = [...sel().options].find(x => x.value === v);
                    const shown = num(/: (\\$[\\d,.]+)/.exec(o.textContent)[1]);
                    sel().value = v;
                    sel().dispatchEvent(new Event("change", { bubbles: true }));
                    seen("8 picker", field + " " + v, shown, total("8"));
                }
            }
        }
        for (const ship of ["G", "A"]) {
            const codes = [...document.querySelectorAll(`tr.pickable[data-ship="${ship}"]`)].map(r => r.dataset.code);
            for (const code of codes) {
                const r = document.querySelector(`tr.pickable[data-ship="${ship}"][data-code="${code}"]`);
                const shown = num(r.querySelector("td:last-child").childNodes[0].textContent);
                const pp = num(r.querySelector(".pp-small").textContent);
                r.click();
                // Same cabin mode: the option card now shows that cabin. Different cabins: the 8 night card's ship line.
                const got = state.mode === "same" ? total(ship) : shipLine(ship === "G" ? "Getaway" : "Aura");
                seen("table " + ship, code + " pp " + pp, shown, got);
            }
        }
        return { out, order };
    }"""
    page = new_page({"width": 360, "height": 800})
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.goto(f"{base}/both/index.html")
    page.wait_for_selector(".card .price-total")
    parties = [(2, []), (2, [15, 7]), (1, [10, 2])]
    offer_sets = [{"bar": b, "dining": d, "plus": p} for b, d, p in ((False, False, False), (True, False, False), (False, True, False), (True, True, False), (True, True, True))]
    offer_pairs = [(o, o) for o in offer_sets] + [(offer_sets[4], offer_sets[0])]
    compared, bad, unsorted, combos = 0, [], [], 0
    for adults, kids in parties:
        for og, oa in offer_pairs:
            for prepay in (False, True):
                for fl in (True, False):
                    for mode in ("same", "different"):
                        cfg = {"adults": adults, "kids": kids, "type": "balcony", "mode": mode, "prepayGratuities": prepay, "flResident": fl,
                               "offers": {"G": og, "A": oa}, "pickG": None, "pickA": None, "diffG": None, "diffA": None}
                        res = page.evaluate(LIST_CHECK, cfg)
                        combos += 1
                        compared += len(res["out"])
                        bad += [(cfg, r) for r in res["out"] if abs(r[2] - r[3]) > 0.005]
                        unsorted += res["order"]
    check(f"list prices = card totals: {compared} prices in {combos} combinations (parties, Free at Sea, Plus, prepay, Florida, both 8 night modes)",
          compared > 5000 and not bad, bad[:3])
    check("list prices: every list cheapest first by the price it shows", not unsorted, unsorted[:3])
    # Florida discount really in the list prices: Getaway BF is $60 x 2 lower with the switch on.
    page.evaluate("""() => { Object.assign(state, { adults: 2, kids: [], type: "balcony", mode: "same", prepayGratuities: false, flResident: true, pickG: "BF",
                              offers: { G: { bar: true, dining: true, plus: false }, A: { bar: true, dining: true, plus: false } } }); render(); }""")
    price_bf = lambda: money(page.inner_text('.card[data-option="G"] button[data-code="BF"] .price'))
    on_bf = price_bf()
    page.click("#flToggle")
    same("list prices include the Florida discount (Getaway BF: 2 guests x $60)", round(price_bf() - on_bf, 2), 120)
    page.click("#flToggle")
    # Labels: what the price is, under each list's title.
    notes = page.eval_on_selector_all(".cat-list-note", "els => els.map(e => e.textContent)")
    same("list labels: card lists, the 8 night pickers and the full tables", sorted(set(notes)), sorted({
        "Each price is the cabin total for 2 guests with your choices, the same as the Total below.",
        "Each price is the 8 night total with your choices: this cabin plus the cabin chosen on the other ship, the same as the Total below.",
        "Each price is the cabin total for 2 guests with your choices, the same as the Total on the Option 1 card.",
        "Each price is the cabin total for 2 guests with your choices, the same as the Total on the Option 2 card."}))
    # A kid without an age: no totals yet, so the lists show NCL's fare with taxes and say so.
    page.evaluate("() => { Object.assign(state, { kids: [null] }); render(); }")
    gbf = next(c for t in gw["types"] for c in t["categories"] if c["code"] == "BF")
    same("list prices before every kid's age is set: NCL's fare with taxes, labelled",
         (price_bf(), page.inner_text('.card[data-option="G"] .cat-list-note')),
         (gbf["by_guests"]["3"]["cabin_total"], "Each price is NCL's fare with taxes for 3 guests. Choose every kid's age above to see each cabin's total with your choices."))
    check("list price checks: no script errors", not errs, errs[:3])
    if SHOTS:
        page.evaluate("() => { Object.assign(state, { kids: [] }); render(); }")
        page.query_selector('.card[data-option="G"]').screenshot(path=os.path.join(SHOTS, "list_prices_getaway.png"))
    page.close()

    browser.close()
srv.shutdown()
shutil.rmtree(site_root, ignore_errors=True)
print("\n" + ("All page checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
