"""Chromium test of index.html at 360 px wide (no NCL calls). Needs Playwright:
    pip install playwright && python -m playwright install chromium
    python3 tools/page_test.py [folder for screenshots]

Two copies of the page are served from a temporary folder: one with today's data/prices.json and
one with the null copy from test_tools.null_copy (Getaway taxes and gratuities and every rate null,
each with its warning). Checks: no sideways scrolling, no script errors, "Prices as of" in Eastern
time with the time of day, the "Not found on NCL today" rules (NOTES.md, "Missing numbers"), and the
prepay gratuities switch (NOTES.md, "Prepay gratuities off by default").
"""
import functools
import http.server
import json
import os
import re
import shutil
import sys
import tempfile
import threading

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = sys.argv[1] if len(sys.argv) > 1 else None
sys.path.insert(0, os.path.join(REPO, "tools"))
import test_tools  # noqa: E402  (null_copy, schema3)

from playwright.sync_api import sync_playwright  # noqa: E402

with open(os.path.join(REPO, "data", "prices.json"), encoding="utf-8") as f:
    real = json.load(f)
sites = {"real": test_tools.schema3(real), "nulls": test_tools.null_copy(real)}


def ksf_copy(data):
    """Kids Sail Free test copy: NCL lists the offer on both ships (Inside to Club Balcony Suite, as
    on the Joy page). The Getaway's BF prices for 3 and 4 guests are set so each extra guest pays
    only the taxes ("prices agree"); the Aura's prices are today's ("prices charge a fare")."""
    d = test_tools.schema3(data)
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


sites["ksf"] = ksf_copy(real)
site_root = tempfile.mkdtemp(prefix="june-page-")
for name, data in sites.items():
    d = os.path.join(site_root, name)
    os.makedirs(os.path.join(d, "data"))
    shutil.copy(os.path.join(REPO, "index.html"), d)
    counts = os.path.join(REPO, "data", "counts.json")
    if os.path.exists(counts):
        shutil.copy(counts, os.path.join(d, "data"))
    with open(os.path.join(d, "data", "prices.json"), "w", encoding="utf-8") as f:
        json.dump(data, f)

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


handler = functools.partial(Quiet, directory=site_root)
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_address[1]}"

money = lambda t: float(re.sub(r"[^\d.]", "", t))
fails = []


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

real_rows = {}
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for name in ("real", "nulls"):
        page = browser.new_page(viewport={"width": 360, "height": 800})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
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
    # shown as "+ $X service charges paid onboard"; on = in the totals. Today's data, 2 adults, Balcony.
    OFF_TITLE, ON_TITLE = "Prepay gratuities (No)", "Prepay gratuities"
    OFF_DESC = "Pay onboard on the last day. Service charges are not in the totals. They're charged to your onboard account and can be removed at Guest Services."
    ON_DESC = "Service charges are paid with the cruise, before you sail. The amount is the same either way."
    R = sites["real"]["rates"]["service_charge"]
    nights = {s["id"].split("-")[0]: s["nights"] for s in sites["real"]["sailings"]}
    want_onboard = [2 * R["standard_per_night"] * nights["getaway"], 2 * R["standard_per_night"] * nights["aura"]]
    want_onboard.append(want_onboard[0] + want_onboard[1])   # 8 nights: both ships' service charges

    def state(page):
        cards = page.query_selector_all(".card")
        notes = [c.query_selector(".onboard-note") for c in cards[:3]]
        return {"checked": page.is_checked("#prepayToggle"),
                "title": page.inner_text("#prepayLabel"), "desc": page.inner_text("#prepayDesc"),
                "totals": [money(c.query_selector(".price-total").inner_text()) for c in cards[:3]],
                "labels": [c.query_selector(".price-label").inner_text() for c in cards[:3]],
                "notes": [n.inner_text() if n else None for n in notes],
                "text": page.inner_text("#app")}

    def is_off(st, where):
        check(f"prepay off ({where}): switch unchecked, title and subtitle", (st["checked"], st["title"], st["desc"]) == (False, OFF_TITLE, OFF_DESC), (st["checked"], st["title"], st["desc"]))
        check(f"prepay off ({where}): '+ $X service charges paid onboard' under each total (8 nights adds both ships)",
              st["notes"] == [f"+ ${int(x) if x == int(x) else x:,} service charges paid onboard (can be removed at Guest Services)" for x in want_onboard], st["notes"])
        check(f"prepay off ({where}): 'Total to pay now'", all(l.startswith("TOTAL TO PAY NOW") or l.startswith("Total to pay now") for l in st["labels"]), st["labels"])
        check(f"prepay off ({where}): service charge line marked onboard, not in the total", st["text"].count("(paid onboard, not in the total)") >= 4, st["text"].count("(paid onboard, not in the total)"))

    def is_on(st, where):
        check(f"prepay on ({where}): switch checked, title and subtitle", (st["checked"], st["title"], st["desc"]) == (True, ON_TITLE, ON_DESC), (st["checked"], st["title"], st["desc"]))
        check(f"prepay on ({where}): no onboard note", st["notes"] == [None, None, None], st["notes"])
        check(f"prepay on ({where}): no line marked onboard", "paid onboard" not in st["text"], "")

    page = browser.new_page(viewport={"width": 360, "height": 800})
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
        page = browser.new_page(viewport={"width": 360, "height": 800})
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
    browser.close()
srv.shutdown()
shutil.rmtree(site_root, ignore_errors=True)
print("\n" + ("All page checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
