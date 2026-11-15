#!/usr/bin/env python3
"""Offline tests for the refresh tools. No NCL calls, standard library only.

  python3 tools/test_tools.py

Runs in the release check workflow (.github/workflows/check.yml) on every push.

Eastern dates (5.0.0): every "done that day" check counts days in America/New_York, never
by UTC date. The real case behind it: a manual run on Oct 12, 2026 at 9:35 PM Eastern saved
prices at 2026-10-13T01:36:25Z, and every timed run on Oct 13 skipped (NOTES.md).

Hold guard (5.0.0): fetch_prices.hold_signal() on every NCL API answer, with real hold signals,
words that only contain the letters, and saved NCL answers in tools/test_data/ (response
bodies only, copied from the owner's local probe of 2026-10-06 and 07: seven Getaway Jun 11
price summaries that list a "HOLD" payment option, and the answer of NCL's manage-cabin call,
which really held a cabin and carries "heldUntil").

NCL ids (5.0.0): fetch_prices.find_sailing() with a stand-in for NCL (cruise page, itinerary
call, fallback to the previous run's ids) and the format check of ncl_ids.

Missing numbers (5.0.0): taxes, gratuities and rates NCL doesn't show are null with a matching
warning, never guessed; tested with a copy of data/prices.json where they are null.

Florida resident rates (5.1.0): tools/fetch_florida.py's weekly cadence (light, full, retry, back
to light, Eastern dates), its runs against a stand-in for NCL (call counts, the light cabins, each
cabin's own amount, the hold guard on signed-in answers, the sail-date stop), the --push guard
(noreply email, main only) and tools/check_florida.py.

CruiseNext offer watch (5.2.0, 5.3.0): tools/fetch_offers.py on NCL's real banner markup (tools/test_data/
cruisenext_doubleup.html, saved 2026-10-28, and cruisenext_tripleup.html, saved 2026-11-07), on
stand-in pages (DoubleUp, TripleUp, QuadUp, a heading and text that disagree), schema 1 files,
the one-time fix for 2026-11-06, and on stand-in pages: started, ended, appeared and
changed, one issue per change with its own marker, retries of an unreported change, pages that
can't be read, wording that can't be read, Eastern dates, and tools/check_offers.py. Also: no
em dash in any tracked file.

Payment data (5.2.0, prices schema 4): deposits, the final payment date and NCL's deposit offer
read from the price summaries and availability answers fetch_prices.py already makes (a saved
NCL answer and whole runs of fetch_prices.py against a stand-in for NCL: the same call count as
before, failed party sizes, kept schema 3 prices, deposit checks that fail), and the format check.
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS)
import decide_run  # noqa: E402
import fetch_counts  # noqa: E402
import fetch_prices as fp  # noqa: E402

TEST_DATA = os.path.join(TOOLS, "test_data")
EM_DASH = chr(0x2014)

FAILED = []


def check(name, got, want):
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {name}: got {got}, expected {want}")
    if not ok:
        FAILED.append(name)


def write(folder, name, saved_at):
    path = os.path.join(folder, name)
    if saved_at is not None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"saved_at": saved_at}, f)
    return path


def decision(folder, event, prices_at, counts_at, now, source=""):
    """Runs tools/decide_run.py itself (as the workflow does) with --now and two small data files."""
    p = write(folder, "prices.json", prices_at)
    c = write(folder, "counts.json", counts_at)
    out = subprocess.run([sys.executable, os.path.join(TOOLS, "decide_run.py"), "--event", event, "--source", source,
                          "--prices", p, "--counts", c, "--now", now],
                         capture_output=True, text=True, env=dict(os.environ, GITHUB_OUTPUT="", GITHUB_STEP_SUMMARY=""))
    if out.returncode != 0:
        return f"exit {out.returncode}: {out.stderr.strip()}"
    lines = dict(l.split("=") for l in out.stdout.splitlines() if l.startswith(("prices=", "counts=")))
    for f in (p, c):
        if os.path.exists(f):
            os.remove(f)
    return lines["prices"] + "," + lines["counts"]


def test_decide():
    FULL, COUNTS, SKIP = "true,true", "false,true", "false,false"
    with tempfile.TemporaryDirectory() as d:
        # The real Oct 12 evening case: saved 9:36 PM Eastern on Oct 12 (Oct 13 by UTC date).
        check("Oct 12 9:36 PM ET refresh, Cloudflare timer Oct 13 6:20 AM ET (10:20Z): full run",
              decision(d, "workflow_dispatch", "2026-10-13T01:36:25Z", "2026-10-13T01:36:31Z", "2026-10-13T10:20:00Z", "timer"), FULL)
        check("same, GitHub schedule Oct 13 6:17 AM ET (10:17Z): full run",
              decision(d, "schedule", "2026-10-13T01:36:25Z", "2026-10-13T01:36:31Z", "2026-10-13T10:17:00Z"), FULL)
        check("same, timer Oct 12 9:50 PM ET (2026-10-13T01:50Z), same evening: skip",
              decision(d, "workflow_dispatch", "2026-10-13T01:36:25Z", "2026-10-13T01:36:31Z", "2026-10-13T01:50:00Z", "timer"), SKIP)
        check("morning refresh 10:22Z, backup schedule 14:47Z same day: skip",
              decision(d, "schedule", "2026-10-14T10:22:34Z", "2026-10-14T10:26:14Z", "2026-10-14T14:47:00Z"), SKIP)
        check("prices done today, counts from yesterday evening (Oct 13 9:40 PM ET): counts only",
              decision(d, "schedule", "2026-10-14T10:22:34Z", "2026-10-14T01:40:21Z", "2026-10-14T14:47:00Z"), COUNTS)
        check("manual run after today's refresh: always a full run",
              decision(d, "workflow_dispatch", "2026-10-14T10:22:34Z", "2026-10-14T10:26:14Z", "2026-10-14T20:00:00Z", "manual"), FULL)
        check("branch push run: prices only, counts skipped",
              decision(d, "push", "2026-10-14T10:22:34Z", "2026-10-14T10:26:14Z", "2026-10-14T20:00:00Z"), "true,false")
        check("branch push run with nothing saved today: still prices only",
              decision(d, "push", "2026-10-13T10:22:34Z", "2026-10-13T10:26:14Z", "2026-10-14T20:00:00Z"), "true,false")
        check("missing data files: full run",
              decision(d, "schedule", None, None, "2026-10-14T10:17:00Z"), FULL)
        # After daylight saving time ends (Nov 1, 2026): Eastern is UTC-5.
        check("after Nov 1: refresh 7:00 AM EST Nov 2, timer 7:30 PM EST Nov 2 (00:30Z Nov 3): skip",
              decision(d, "workflow_dispatch", "2026-11-02T12:00:00Z", "2026-11-02T12:04:00Z", "2026-11-03T00:30:00Z", "timer"), SKIP)
        check("after Nov 1: refresh 7:30 PM EST Nov 2 (00:30Z Nov 3), schedule 5:17 AM EST Nov 3: full run",
              decision(d, "schedule", "2026-11-03T00:30:00Z", "2026-11-03T00:34:00Z", "2026-11-03T10:17:00Z"), FULL)
        # Sail-date stop: Jun 11, 2027 (Eastern).
        check("last refresh Jun 9, 2027; timer Jun 10 10:00 PM EDT (02:00Z Jun 11): still runs",
              decision(d, "workflow_dispatch", "2027-06-09T10:22:00Z", "2027-06-09T10:26:00Z", "2027-06-11T02:00:00Z", "timer"), FULL)
        check("refreshed Jun 10, 2027 6:22 AM EDT; timer Jun 10 10:00 PM EDT (02:00Z Jun 11): skip, same Eastern day",
              decision(d, "workflow_dispatch", "2027-06-10T10:22:00Z", "2027-06-10T10:26:00Z", "2027-06-11T02:00:00Z", "timer"), SKIP)
        check("Jun 11, 2027 6:20 AM EDT, timer: stopped",
              decision(d, "workflow_dispatch", "2027-06-10T10:22:00Z", "2027-06-10T10:26:00Z", "2027-06-11T10:20:00Z", "timer"), SKIP)
        check("Jun 11, 2027, manual run: stopped too",
              decision(d, "workflow_dispatch", "2027-06-10T10:22:00Z", "2027-06-10T10:26:00Z", "2027-06-11T15:00:00Z", "manual"), SKIP)
        check("Jun 14, 2027, schedule: stopped",
              decision(d, "schedule", "2027-06-10T10:22:00Z", "2027-06-10T10:26:00Z", "2027-06-14T10:17:00Z"), SKIP)
    check("stop date is the Getaway's sail date", str(decide_run.STOP_DATE), "2027-06-11")


def test_counts_cadence():
    utc = lambda s: dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    prev = lambda at: {"last_full_sweep": at}
    # Full sweep Oct 12 9:40 PM ET (Oct 13 by UTC). Oct 15 morning is 3 Eastern days later (only 2 UTC days).
    check("full sweep Oct 12 9:40 PM ET, auto on Oct 15 6:20 AM ET: full",
          fetch_counts.choose_mode("auto", prev("2026-10-13T01:40:21Z"), utc("2026-10-15T10:20:00Z"))[0], "full")
    check("full sweep Oct 12 9:40 PM ET, auto on Oct 14 6:20 AM ET: light",
          fetch_counts.choose_mode("auto", prev("2026-10-13T01:40:21Z"), utc("2026-10-14T10:20:00Z"))[0], "light")
    check("full sweep Oct 12 3:49 PM ET, auto on Oct 15 10:20 PM ET (02:20Z Oct 16): full",
          fetch_counts.choose_mode("auto", prev("2026-10-12T19:49:58Z"), utc("2026-10-16T02:20:00Z"))[0], "full")
    check("after Nov 1: full sweep Nov 2 7:30 PM EST (00:30Z Nov 3), auto Nov 4 10:00 PM EST (03:00Z Nov 5): light",
          fetch_counts.choose_mode("auto", prev("2026-11-03T00:30:00Z"), utc("2026-11-05T03:00:00Z"))[0], "light")


def saved(name):
    with open(os.path.join(TEST_DATA, name + ".json"), encoding="utf-8") as f:
        return json.load(f)


# The 2026-10-06 and 07 Getaway price summaries (the 1 guest ones of 2026-11-15 are tested in test_saved_one_guest).
SAVED_PRICE_SUMMARIES = sorted(f[:-5] for f in os.listdir(TEST_DATA) if f.startswith("price_summary_getaway_B4"))


def test_hold_signal():
    sig = fp.hold_signal
    # Real hold signals: each one must be found.
    real = {
        "heldUntil key": {"results": [{"cabin": {"heldUntil": "2000-01-01T00:00:00Z"}}]},
        "holdId key": {"holdId": 12345},
        "onHold key": {"cabin": {"onHold": True}},
        "cabinHolds key": {"cabinHolds": []},
        "isHeld key": {"isHeld": False},
        "HOLD_EXPIRY key": {"HOLD_EXPIRY": "x"},
        "hold key": {"hold": None},
        "reservationId key": {"reservationId": "ABC"},
        "reservation_number key": {"guests": [{"reservation_number": 1}]},
        "ReservationCode key": {"ReservationCode": "x"},
        "reservationNo key": {"reservationNo": "x"},
        "status HOLD": {"status": "HOLD"},
        "status ON_HOLD": {"status": "ON_HOLD"},
        "text On Hold": {"message": "Your stateroom is On Hold"},
        "text recommendAndHold": {"action": "recommendAndHold"},
        "text heldUntil": {"note": "cabin heldUntil noon"},
        "hold in a list": {"x": [1, {"y": ["fine", "hold"]}]},
        "plain text hold": "hold",
    }
    for name, answer in real.items():
        check(f"real hold signal found: {name}", sig(answer) is not None, True)
    # Ordinary words that only contain the letters: never a signal.
    ordinary = {
        "household": {"text": "One household per stateroom"},
        "cardholder": {"text": "The cardholder must be 21"},
        "cardHolder key": {"cardHolder": "x"},
        "placeholder key and value": {"emailPlaceholder": "placeholder"},
        "threshold": {"maxThresholdGuests": 4, "text": "threshold"},
        "stakeholder": {"text": "stakeholder"},
        "holds up to": {"description": "This stateroom holds up to 4 guests"},
        "holder, holiday, upholstery": {"text": "Holder Holiday upholstery beholden"},
        "reservationOwner key (age test guests)": {"guests": [{"reservationOwner": True}]},
    }
    for name, answer in ordinary.items():
        check(f"ordinary word not a signal: {name}", sig(answer), None)
    # The price-summary payment option, and only that.
    pay = {"staterooms": [{"paymentOptions": [{"paymentType": "DEPOSIT"}, {"isDeposit": True, "paymentType": "HOLD"}]}]}
    allowed = []
    check("price summary: paymentOptions paymentType HOLD allowed", sig(pay, price_summary=True, allowed=allowed), None)
    check("price summary: the allowed option is reported for the log", allowed, [fp.PAYMENT_HOLD_PATH])
    check("same answer from any other call (availability): stops", sig(pay) is not None, True)
    with_held = {"staterooms": [{"paymentOptions": [{"paymentType": "HOLD"}], "heldUntil": "x"}]}
    check("price summary: heldUntil key in the same answer still stops", sig(with_held, price_summary=True) is not None, True)
    other_hold = {"staterooms": [{"paymentOptions": [{"paymentType": "HOLD"}], "status": "HOLD"}]}
    check("price summary: another HOLD value in the same answer still stops", sig(other_hold, price_summary=True) is not None, True)
    for name, answer in {
        "paymentType ON_HOLD": {"staterooms": [{"paymentOptions": [{"paymentType": "ON_HOLD"}]}]},
        "paymentType Hold (not exactly HOLD)": {"staterooms": [{"paymentOptions": [{"paymentType": "Hold"}]}]},
        "paymentType HOLD outside staterooms": {"paymentOptions": [{"paymentType": "HOLD"}]},
        "paymentType HOLD outside paymentOptions": {"staterooms": [{"paymentType": "HOLD"}]},
        "holdId key next to the option": {"staterooms": [{"paymentOptions": [{"paymentType": "HOLD", "holdId": 1}]}]},
        "reservationId next to the option": {"staterooms": [{"paymentOptions": [{"paymentType": "HOLD"}]}], "reservationId": "x"},
    }.items():
        check(f"price summary: {name} still stops", sig(answer, price_summary=True) is not None, True)

    # Saved NCL answers.
    check("7 saved Getaway price summaries found", len(SAVED_PRICE_SUMMARIES), 7)
    for name in SAVED_PRICE_SUMMARIES:
        answer = saved(name)
        allowed = []
        check(f"saved {name}: no hold signal as a price summary", sig(answer, price_summary=True, allowed=allowed), None)
        check(f"saved {name}: lists the HOLD payment option", allowed, [fp.PAYMENT_HOLD_PATH])
        check(f"saved {name}: would stop if it came from another call", sig(answer) is not None, True)
        check(f"saved {name}: old broad check sees 'hold' too", bool(fp.HOLD_IN_RESPONSE.search(json.dumps(answer).encode())), True)
    hold = saved("manage_cabin_REAL_HOLD_2026-10-06")
    check("saved manage-cabin answer (a real hold): found", sig(hold), "key results.cabin.heldUntil")
    check("saved manage-cabin answer: found even as a price summary", sig(hold, price_summary=True), "key results.cabin.heldUntil")
    check("saved manage-cabin answer: old broad check finds it too", bool(fp.HOLD_IN_RESPONSE.search(json.dumps(hold).encode())), True)


class FakeOpener:
    """Stands in for urllib's opener: returns a saved answer, counts calls, never touches the network."""
    def __init__(self, answer):
        self.body, self.calls = json.dumps(answer).encode(), 0

    def open(self, req, timeout=None):
        self.calls += 1
        body = self.body

        class Res:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return body
        return Res()


def expect_stop(name, url, opener, body):
    fp._no_redirect_opener = opener
    try:
        fp.request(url, body)
        check(name, "no stop", "HoldSignal")
    except fp.HoldSignal:
        check(name, "HoldSignal", "HoldSignal")


def test_request_guards():
    keep = (fp._no_redirect_opener, fp.urllib.request.build_opener, fp.log, fp.PAUSE_SECONDS)
    logs = []
    fp.log, fp.PAUSE_SECONDS = logs.append, 0
    try:
        body = {"packageId": "1"}
        summary = saved(SAVED_PRICE_SUMMARIES[0])
        fp._no_redirect_opener = FakeOpener(summary)
        check("request(): saved price summary passes", fp.request(fp.PRICE_SUMMARY_URL, body) == summary, True)
        check("request(): logs the HOLD payment option", logs[-1:], ["  " + fp.PAYMENT_HOLD_NOTE])

        fake = FakeOpener(summary)
        expect_stop("request(): HOLD option in an availability answer stops", fp.AVAILABILITY_URL, fake, body)
        check("request(): a hold signal is not retried (1 call)", fake.calls, 1)
        expect_stop("request(): saved real hold answer stops the run", fp.PRICE_SUMMARY_URL,
                    FakeOpener(saved("manage_cabin_REAL_HOLD_2026-10-06")), body)

        fake = FakeOpener({"sailing": {"note": "household"}})
        fp.urllib.request.build_opener = lambda *a: fake
        check("request(): GET answer with 'household' passes",
              fp.request(fp.ROUTE_EVENTS_URL.format(package_id="1")), {"sailing": {"note": "household"}})

        fake = FakeOpener({})
        fp._no_redirect_opener = fake
        fp.urllib.request.build_opener = lambda *a: fake
        for url in ["https://www.ncl.com/api/vacation-builder/cabin/manage-cabin",
                    "https://www.ncl.com/booking/api/recommended-cabin-hold",
                    "https://www.ncl.com/api/x/HOLD"]:
            try:
                fp.request(url, body)
                check(f"address guard refuses {url}", "called", "refused")
            except RuntimeError as e:
                check(f"address guard refuses {url}", "refused" if "Refusing" in str(e) else str(e), "refused")
        check("address guard: refused before any call", fake.calls, 0)
        check("HoldSignal is a RuntimeError (callers that stop on errors still stop)", issubclass(fp.HoldSignal, RuntimeError), True)
    finally:
        fp._no_redirect_opener, fp.urllib.request.build_opener, fp.log, fp.PAUSE_SECONDS = keep


class RedirectOpener:
    """Answers the first `redirects` calls with HTTP 302 to ncl.com.mx, then the saved answer."""
    def __init__(self, redirects, answer):
        self.redirects, self.ok, self.calls = redirects, FakeOpener(answer), 0

    def open(self, req, timeout=None):
        self.calls += 1
        if self.calls <= self.redirects:
            raise fp.urllib.error.HTTPError(req.full_url, 302, "Found",
                                            {"Location": "https://www.ncl.com.mx/api/vacation-builder/cabin/availability"}, None)
        return self.ok.open(req, timeout)


def test_request_redirects():
    """Oct 21, 2026: a 302 to ncl.com.mx crashed request() (UnboundLocalError) instead of retrying."""
    keep = (fp._no_redirect_opener, fp.log, fp.PAUSE_SECONDS, fp.RETRY_WAITS)
    logs = []
    fp.log, fp.PAUSE_SECONDS, fp.RETRY_WAITS = logs.append, 0, [0] * len(fp.RETRY_WAITS)
    try:
        body = {"stateroomSearchFilter": {}}
        fake = RedirectOpener(99, {})
        fp._no_redirect_opener = fake
        try:
            fp.request(fp.CABIN_AVAILABILITY_URL, body, raw=True)
            check("request(): 302 every time fails", "returned", "RuntimeError")
        except fp.HoldSignal:
            check("request(): 302 every time fails", "HoldSignal", "RuntimeError")
        except RuntimeError as e:
            check("request(): 302 every time fails cleanly", "Request failed" in str(e) and "ncl.com.mx" in str(e), True)
        check("request(): 302 is retried, 4 calls in all", fake.calls, len(fp.RETRY_WAITS) + 1)
        fake = RedirectOpener(1, {"results": {}})
        fp._no_redirect_opener = fake
        res, raw = fp.request(fp.CABIN_AVAILABILITY_URL, body, raw=True)
        check("request(): one 302 then an answer succeeds", (res, fake.calls), ({"results": {}}, 2))
    finally:
        fp._no_redirect_opener, fp.log, fp.PAUSE_SECONDS, fp.RETRY_WAITS = keep


def ms(iso):
    return int(dt.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


def cruise_page(sailings):
    """A cruise page as NCL serves it: the sailing list as HTML-escaped JSON in data-pricing-sailings."""
    import html as h
    return f'<div class="x" data-pricing-sailings="{h.escape(json.dumps(sailings), quote=True)}"></div>'


def itinerary(package_id, sail_start, ship="GETAWAY", nights=3, sailing_id=60533):
    return {"sailing": {"packageId": int(package_id), "sailStartDate": sail_start, "sailingId": sailing_id},
            "ship": {"code": ship}, "duration": nights, "destinations": [{"code": "BAHAMAS"}, {"code": "WEEKEND"}]}


class FakeNCL:
    """Answers fp.request() calls from a table, counts them, never touches the network."""
    def __init__(self, page=None, itin=None):
        self.page, self.itin, self.calls = page, itin, []

    def __call__(self, url, body=None, raw=False, page=False):
        self.calls.append(url)
        if page:
            if isinstance(self.page, Exception):
                raise self.page
            return self.page
        return self.itin


def lookup(fake, cfg, prev=None):
    keep, keep_log = fp.request, fp.log
    fp.request, fp.log = fake, (lambda m: None)
    try:
        return fp.find_sailing(cfg, prev)
    except Exception as e:
        return type(e).__name__, str(e)
    finally:
        fp.request, fp.log = keep, keep_log


def test_find_sailing():
    G = next(c for c in fp.SAILINGS if c["id"].startswith("getaway"))
    A = next(c for c in fp.SAILINGS if c["id"].startswith("aura"))
    check("SAILINGS: no typed-in packageId or itinerary code",
          [k for c in fp.SAILINGS for k in ("package_id", "itinerary_code", "sailing_id") if k in c], [])
    check("SAILINGS: fixed facts only", [(c["ship_code"], c["depart"], c["nights"], c["itinerary_prefix"]) for c in fp.SAILINGS],
          [("GETAWAY", "2027-06-11", 3, "GETAWAY3MIA"), ("AURA", "2027-06-14", 5, "AURA5MIA")])
    page = cruise_page([
        {"itineraryCode": "GETAWAY3MIANPINASMIA", "packageId": 24223000, "departureDate": ms("2027-06-04T04:00:00Z")},
        {"itineraryCode": "GETAWAY7MIAXXXXXXXX", "packageId": 99, "departureDate": ms("2027-06-11T04:00:00Z")},
        {"itineraryCode": "GETAWAY3MIANPINASMIA", "packageId": 24223992, "departureDate": ms("2027-06-11T04:00:00Z")},
    ])
    good = itinerary("24223992", "2027-06-11T00:00:00")
    fake = FakeNCL(page, good)
    ids, warns = lookup(fake, G)
    check("cruise page lists the sailing: packageId from the page", (ids["itinerary_code"], ids["package_id"]), ("GETAWAY3MIANPINASMIA", "24223992"))
    check("cruise page lists the sailing: other dates and other itineraries skipped", ids["package_id"] != "99", True)
    check("cruise page lists the sailing: sailingId and ship from the itinerary call", (ids["sailing_id"], ids["ship_code"], ids["duration"]), ("60533", "GETAWAY", 3))
    check("cruise page lists the sailing: no warning", warns, [])
    check("cruise page lists the sailing: 2 calls (cruise page, itinerary)", len(fake.calls), 2)
    check("cruise page address", fake.calls[0], "https://www.ncl.com/cruises/GETAWAY3MIANPINASMIA")
    # Departure given as UTC midnight (a Miami date of the day before) still matches the sail date.
    fake = FakeNCL(cruise_page([{"itineraryCode": "GETAWAY3MIANPINASMIA", "packageId": 24223992, "sailStartDate": ms("2027-06-11T00:00:00Z")}]), good)
    check("sail date written as UTC midnight: found", lookup(fake, G)[0]["package_id"], "24223992")

    prev = {"itinerary_code": "GETAWAY3MIANPINASMIA", "package_id": "24223992"}
    fake = FakeNCL(RuntimeError("NCL answered HTTP 403"), good)
    ids, warns = lookup(fake, G, prev)
    check("cruise page fails: previous run's ids, confirmed by the itinerary call", (ids["package_id"], ids["found_on"]), ("24223992", "previous run"))
    check("cruise page fails: a warning names the ship", len(warns) == 1 and warns[0].startswith("Getaway:") and "previous run" in warns[0], True)
    check("cruise page fails: still 2 calls (the page is never retried)", len(fake.calls), 2)
    fake = FakeNCL(cruise_page([]), good)
    check("cruise page doesn't list the sailing: previous run's ids", lookup(fake, G, prev)[0]["found_on"], "previous run")
    fake = FakeNCL("<html>no list</html>", good)
    check("cruise page has no sailing list: previous run's ids", lookup(fake, G, prev)[0]["found_on"], "previous run")
    fake = FakeNCL(RuntimeError("down"), good)
    check("cruise page fails and no previous ids: the sailing fails", lookup(fake, G)[0], "RuntimeError")
    check("cruise page fails and no previous ids: no itinerary call", len(fake.calls), 1)

    for name, itin in {
        "itinerary for another ship": itinerary("24223992", "2027-06-11T00:00:00", ship="BREAKAWAY"),
        "itinerary with another length": itinerary("24223992", "2027-06-11T00:00:00", nights=4),
        "itinerary on another date": itinerary("24223992", "2027-06-12T00:00:00"),
        "itinerary for another packageId": itinerary("11111111", "2027-06-11T00:00:00"),
        "itinerary without a sailingId": itinerary("24223992", "2027-06-11T00:00:00", sailing_id=None),
    }.items():
        check(f"{name}: the sailing fails", lookup(FakeNCL(page, itin), G)[0], "RuntimeError")

    aura_page = cruise_page([{"itineraryCode": "AURA5MIAPOPNPIMIA", "packageId": 25729291, "departureDate": ms("2027-06-14T04:00:00Z")}])
    ids, warns = lookup(FakeNCL(aura_page, itinerary("25729291", "2027-06-14T00:00:00", ship="AURA", nights=5, sailing_id=62344)), A)
    check("Aura: ids from its own cruise page and itinerary", (ids["itinerary_code"], ids["package_id"], ids["sailing_id"], ids["ship_code"]),
          ("AURA5MIAPOPNPIMIA", "25729291", "62344", "AURA"))
    check("Aura cruise page address", fp.CRUISE_PAGE_URL.format(code=A["start_pages"][0]), "https://www.ncl.com/cruises/AURA5MIAPOPNPIMIA")

    check("previous ids from a schema 3 file", fp.previous_ids({"ncl_ids": {"itinerary_code": "X", "package_id": "1"}, "itinerary_code": "Y", "package_id": "2"}),
          {"itinerary_code": "X", "package_id": "1"})
    check("previous ids from the schema 2 file on main (no ncl_ids yet)", fp.previous_ids({"itinerary_code": "GETAWAY3MIANPINASMIA", "package_id": "24223992"}),
          {"itinerary_code": "GETAWAY3MIANPINASMIA", "package_id": "24223992"})
    check("no previous file: no previous ids", fp.previous_ids(None), None)

    # A cruise page is a web page: not checked for hold signals (as before for web pages), but the
    # address guard applies, and it is tried once only.
    keep = (fp.urllib.request.build_opener, fp.PAUSE_SECONDS, fp.log)
    fp.PAUSE_SECONDS, fp.log = 0, (lambda m: None)
    try:
        opener = FakeOpener("placeholder household hold")
        opener.body = b'<div data-pricing-sailings="[]">Hold your spot</div>'
        fp.urllib.request.build_opener = lambda *a: opener
        check("web page text is returned as text", fp.request("https://www.ncl.com/cruises/X", page=True).startswith("<div"), True)

        class Down:
            calls = 0

            def open(self, req, timeout=None):
                Down.calls += 1
                raise OSError("network down")
        fp.urllib.request.build_opener = lambda *a: Down()
        try:
            fp.request("https://www.ncl.com/cruises/X", page=True)
        except RuntimeError:
            pass
        check("a failed web page is not retried (1 call)", Down.calls, 1)
    finally:
        fp.urllib.request.build_opener, fp.PAUSE_SECONDS, fp.log = keep


def test_check_prices_ids():
    import check_prices
    with open(os.path.join(os.path.dirname(TOOLS), "data", "prices.json"), encoding="utf-8") as f:
        old = json.load(f)
    if old.get("schema_version") == 3:
        check("release check accepts the committed schema 3 file", check_prices.check(old, allow_schema_3=True), [])
        check("the refresh's check of a new file never accepts schema 3", "schema_version must be 4" in check_prices.check(old), True)
        bad = json.loads(json.dumps(old))
        bad["sailings"][0]["ncl_ids"]["package_id"] = "1"
        check("release check of a schema 3 file still checks ncl_ids", any("does not match" in e for e in check_prices.check(bad, allow_schema_3=True)), True)
    if old.get("schema_version") == 4:
        check("release check accepts the committed schema 4 file", check_prices.check(old, allow_schema_4=True), [])
        check("the refresh's check of a new file never accepts schema 4", "schema_version must be 5" in check_prices.check(old), True)
        bad = json.loads(json.dumps(old))
        bad["sailings"][0]["ncl_ids"]["package_id"] = "1"
        check("release check of a schema 4 file still checks ncl_ids", any("does not match" in e for e in check_prices.check(bad, allow_schema_4=True)), True)
        bad = json.loads(json.dumps(old))
        bad["sailings"][0]["payment"]["by_guests"]["2"]["deposit"] = None
        check("release check of a schema 4 file still checks the payment data", any("empty deposit needs" in e for e in check_prices.check(bad, allow_schema_4=True)), True)
    new = schema5(old)
    new["warnings"] = []
    for s in new["sailings"]:
        s["ncl_ids"] = {"itinerary_code": s["itinerary_code"], "package_id": s["package_id"], "sailing_id": "60533",
                        "ship_code": s["ship_short"].upper(), "found_on": f"https://www.ncl.com/cruises/{s['itinerary_code']}",
                        "checked_at": "2026-10-15T10:20:00Z"}
        s.setdefault("kids_sail_free", None)
    check("schema 5 file with ncl_ids passes", check_prices.check(new), [])
    bad = json.loads(json.dumps(new))
    bad["sailings"][0]["ncl_ids"]["package_id"] = "1"
    check("ncl_ids that don't match the sailing fail", any("does not match" in e for e in check_prices.check(bad)), True)
    prev = json.loads(json.dumps(new))
    prev["sailings"][1]["ncl_ids"]["found_on"] = "previous run"
    check("ids from the previous run without a warning fail", any("without a warning" in e for e in check_prices.check(prev)), True)
    prev["warnings"] = ["Aura: could not find the sailing on NCL's cruise page (x); tried the previous run's ids"]
    check("ids from the previous run with the warning pass", check_prices.check(prev), [])


def schema4(data):
    """A schema 4 copy of a price file. A schema 3 file (the committed one until the first refresh
    after 5.2.0) gets the payment data fetch_prices.py would write from its price summaries, with
    NCL's rules as the 2026-10-28 research saw them: $50 per guest up to Club Balcony Suite, 10% of
    the cruise fare for Suite and Haven, final payment 120 days before sailing, 2-For-1 Deposits."""
    d = json.loads(json.dumps(data))
    d["schema_version"] = 4
    d.setdefault("warnings", [])
    d["checks"].setdefault("deposits", [])
    d.setdefault("deposit_rules", dict({"suite_haven_types": fp.DEPOSIT_PERCENT_TYPES, "source": fp.DEPOSIT_RULE_SOURCE,
                                        "percent_of_fare": fp.DEPOSIT_PERCENT}, **fp.DEPOSIT_RESEARCH))
    for s in d["sailings"]:
        s.setdefault("kids_sail_free", None)
        s.setdefault("ncl_ids", {"itinerary_code": s["itinerary_code"], "package_id": s["package_id"], "sailing_id": "1",
                                 "ship_code": s["ship_short"].upper(), "found_on": "https://www.ncl.com/cruises/x",
                                 "checked_at": "2026-10-15T10:20:00Z"})
        if "payment" in s:
            continue
        by = {}
        for ps in s["price_summaries"]:
            pct = ps["type"] in fp.DEPOSIT_PERCENT_TYPES
            ps.update(deposit=round(ps["fare_total"] * fp.DEPOSIT_PERCENT / 100, 2) if pct else 50 * ps["guests"],
                      deposit_due_hours=23 if pct else 76,
                      final_payment_due=(dt.date.fromisoformat(s["depart"]) - dt.timedelta(days=120)).isoformat())
            by[str(ps["guests"])] = {"deposit": ps["deposit"], "deposit_type": ps["type"], "deposit_category": ps["category"],
                                     "due_hours": ps["deposit_due_hours"], "as_of": s["party_sizes"][str(ps["guests"])]["as_of"], "why": None}
        s["payment"] = {"source": "NCL price-summary paymentOptions",
                        "final_payment_due": s["price_summaries"][0]["final_payment_due"],
                        "standard_deposit_per_guest": 50, "standard_deposit_checked_at": d["saved_at"][:10],
                        "by_guests": by,
                        "deposit_offer": {"title": "2-For-1 Deposits", "short": None, "codes": [], "types": [],
                                          "description": "Lock-in this vacation today with half off deposits for every two guests on your reservation.",
                                          "checked_at": d["saved_at"]}}
    return d


# Solo cabins for 1 guest as NCL priced them in the probe of 2026-11-15 (cabin total with taxes);
# None is sold out. Regular cabins for 1 guest: NCL charged twice the per guest fare for 2 guests
# on every category of both ships, plus taxes for one guest ("Free 2nd Guest").
PROBE_SOLO = {"getaway-2027-06-11": {"T1": 539, "IT": 509, "OT": 569, "BT": 639},
              "aura-2027-06-14": {"T1": 2089, "IT": None, "OT": None, "BT": 3109}}


def schema5(data):
    """A schema 5 copy of a price file (5.4.0, party size 1). A schema 4 file (the committed one
    until the first refresh after 5.4.0) gets 1 guest prices shaped like NCL's answers in the probe
    of 2026-11-15: the solo prices above, regular cabins at twice the 2 guest fare per guest plus
    taxes for one, and the two 1 guest price summaries (regular and solo, $50 deposit in 84 hours)
    with their formula checks, as fetch_prices.py would write them."""
    d = schema4(data)
    if d["schema_version"] == 5:
        return d
    d["schema_version"] = 5
    d["guest_counts"] = [1, 2, 3, 4, 5]
    d["checks"]["one_guest"] = []
    d["deposit_rules"]["one_guest_confirmed_on"] = None
    for s in d["sailings"]:
        tax = s["taxes_per_guest"] or 0
        grat = s["gratuities"]
        for g, st in s["party_sizes"].items():
            st["checked"] = True
        s["party_sizes"] = {"1": {"updated": True, "checked": True, "as_of": s["party_sizes"]["2"]["as_of"], "why": None}, **s["party_sizes"]}
        picks = {}
        for t in s["types"]:
            for c in t["categories"]:
                two = c["by_guests"]["2"]
                if c["solo"]:
                    price = PROBE_SOLO[s["id"]].get(c["code"])
                    one = ({"available": True, "sold_out": False, "price_pp": float(price), "cabin_total": price} if price
                           else {"available": False, "sold_out": True, "reason": "Sold out"})
                elif two["available"]:
                    pp = round(2 * (two["price_pp"] - tax) + tax, 2)
                    one = {"available": True, "sold_out": False, "price_pp": pp, "cabin_total": int(round(pp))}
                else:
                    one = {"available": False, "sold_out": two["sold_out"], "reason": "Sold out" if two["sold_out"] else "Sold out for this party size"}
                c["by_guests"] = {"1": one, **c["by_guests"]}
                if one["available"]:
                    kind = "solo" if c["solo"] else "regular"
                    if kind not in picks or one["price_pp"] < picks[kind][2]["price_pp"]:
                        picks[kind] = (t, c, one)
        for x in s["price_summaries"]:
            x.setdefault("kind", "regular")
        two_sum = next(x for x in s["price_summaries"] if x["guests"] == 2)
        ones = []
        for kind in ("regular", "solo"):
            if kind not in picks:
                continue
            t, c, one = picks[kind]
            bar = grat["open_bar"]["per_guest"] if grat else 0
            dining = grat["specialty_dining"]["per_guest"] if grat else 0
            ones.append({"guests": 1, "type": t["code"], "category": c["code"],
                         "fare_code": "CHOALL4M" if t["code"] in ("SUITE", "HAVEN") else "ALL4CHO",
                         "fare_total": one["cabin_total"] - tax, "fare_per_guest": [one["cabin_total"] - tax], "fare_title": "Free 2nd Guest",
                         "taxes_per_guest": [tax], "open_bar": {"title": "Unlimited Open Bar", "per_guest": [bar]},
                         "specialty_dining": {"title": grat["specialty_dining"]["title"] if grat else "Specialty Dining", "per_guest": [dining]},
                         "grand_total": one["cabin_total"] + bar + dining, "deposit": 50.0, "deposit_due_hours": 84,
                         "final_payment_due": two_sum.get("final_payment_due"), "kind": kind})
            d["checks"]["formula"].append({"sailing": s["id"], "guests": 1, "kind": kind, "category": c["code"],
                                           "expected": one["cabin_total"] + bar + dining, "ncl_total": one["cabin_total"] + bar + dining, "ok": True})
            d["checks"]["one_guest"].append({"sailing": s["id"], "kind": kind, "category": c["code"], "ok": True, "why": None})
            d["checks"]["deposits"].append({"sailing": s["id"], "guests": 1, "kind": kind, "type": t["code"], "category": c["code"],
                                            "rule": fp.ONE_GUEST_RULE, "deposit": 50.0, "expected": 50, "ok": True})
        s["price_summaries"] = ones + s["price_summaries"]
        for c in d["checks"]["formula"]:
            c.setdefault("kind", "regular")
        pay = s["payment"]
        entry = lambda x: {"deposit": x["deposit"], "deposit_type": x["type"], "deposit_category": x["category"],
                           "due_hours": x["deposit_due_hours"], "as_of": s["party_sizes"]["1"]["as_of"], "why": None}
        pay["by_guests"] = {"1": entry(ones[0]), **pay["by_guests"]}
        pay["solo_1_guest"] = entry(ones[1]) if len(ones) > 1 else None
        pay["standard_deposit_1_guest_ok"] = True
        pay["deposit_offer_1_guest"] = dict(pay["deposit_offer"]) if pay["deposit_offer"] else None
        types = {t["code"]: {"categories": {c["code"]: c for c in t["categories"]}} for t in s["types"]}
        s["single_supplement"] = fp.single_supplement(types, s["taxes_per_guest"], {"regular": ones[0]}, s["party_sizes"])
    return d


def not_checked_1(data, ship="getaway"):
    """A schema 5 copy where party size 1 is not checked today on one ship (5.4.0): no usable 1
    guest prices, as fetch_prices.py writes it after a failure with nothing to keep."""
    d = schema5(data)
    s = next(x for x in d["sailings"] if x["id"].startswith(ship))
    why = "RuntimeError: NCL answered HTTP 500; the previous file has no prices for 1 guest"
    s["party_sizes"]["1"] = {"updated": False, "checked": False, "as_of": None, "why": why}
    for t in s["types"]:
        for c in t["categories"]:
            c["by_guests"]["1"] = {"available": False, "sold_out": False, "reason": fp.NOT_CHECKED}
    s["price_summaries"] = [x for x in s["price_summaries"] if x["guests"] != 1]
    d["checks"]["formula"] = [c for c in d["checks"]["formula"] if not (c["sailing"] == s["id"] and c["guests"] == 1)]
    d["checks"]["one_guest"] = [c for c in d["checks"]["one_guest"] if c["sailing"] != s["id"]]
    d["checks"]["deposits"] = [c for c in d["checks"]["deposits"] if not (c["sailing"] == s["id"] and c["guests"] == 1)]
    s["payment"]["by_guests"]["1"] = {"deposit": None, "deposit_type": None, "deposit_category": None, "due_hours": None, "as_of": None,
                                      "why": "prices for 1 guest not checked today"}
    s["payment"].update(solo_1_guest=None, standard_deposit_1_guest_ok=None, deposit_offer_1_guest=None)
    s["single_supplement"] = None
    d["warnings"] += [f"{s['ship_short']}: prices for 1 guest not checked today ({why}); 1 guest left out",
                      f"{s['ship_short']}: no deposit for 1 guest (prices for 1 guest not checked today); left empty"]
    return d


def null_copy(data):
    """The test copy for "Not found on NCL today": Getaway taxes and gratuities, and every rate,
    null, each with the warning fetch_prices.py would write."""
    d = schema5(data)
    g = next(s for s in d["sailings"] if s["id"].startswith("getaway"))
    g["taxes_per_guest"] = None
    g["gratuities"] = None
    d["warnings"] += ["Getaway: no tax line in NCL's price summary today; taxes per guest left empty",
                      "Getaway: Free at Sea gratuities not found on NCL today (test); left empty"]
    for c in d["checks"]["ages"]:
        if c["sailing"] == g["id"]:
            c.clear()
            c.update({"sailing": g["id"], "party": "1 adult, 15, 7", "ok": None, "why": "RuntimeError: test"})
    d["checks"]["rates"] = [c for c in d["checks"].get("rates", []) if c["sailing"] != g["id"]]
    for key in ("free_at_sea_plus", "open_bar", "service_charge"):
        d["rates"][key] = None
        d["rate_warnings"].append(f"{key}: could not read https://www.ncl.com/ (test); left empty")
    return d


def test_missing_numbers():
    import check_prices
    with open(os.path.join(os.path.dirname(TOOLS), "data", "prices.json"), encoding="utf-8") as f:
        real = json.load(f)
    nulls = null_copy(real)
    check("null copy: taxes, gratuities and rates null, each with a warning, passes the format check", check_prices.check(nulls), [])

    def without(pred):
        d = json.loads(json.dumps(nulls))
        d["warnings"] = [w for w in d["warnings"] if not pred(w)]
        d["rate_warnings"] = [w for w in d["rate_warnings"] if not pred(w)]
        return check_prices.check(d)
    check("null taxes without a warning: rejected", any("taxes_per_guest is empty without a warning" in e for e in without(lambda w: "tax line" in w)), True)
    check("null gratuities without a warning: rejected", any("gratuities are empty without a warning" in e for e in without(lambda w: "gratuities" in w)), True)
    for key in ("free_at_sea_plus", "open_bar", "service_charge"):
        check(f"null rates.{key} without a warning: rejected", any(f"rates.{key} is empty without a warning" in e for e in without(lambda w, k=key: w.startswith(k + ":"))), True)
    d = json.loads(json.dumps(nulls))
    d["warnings"] = [w.replace("Getaway:", "Aura:") for w in d["warnings"]]
    check("a warning for the other ship doesn't count", any("without a warning" in e for e in check_prices.check(d)), True)
    d = json.loads(json.dumps(nulls))
    next(c for c in d["checks"]["ages"] if c["sailing"].startswith("getaway"))["ok"] = True
    check("null gratuities with an age check that says ok: rejected", any("age check says ok" in e for e in check_prices.check(d)), True)
    d = json.loads(json.dumps(nulls))
    next(c for c in d["checks"]["ages"] if c["sailing"].startswith("getaway"))["why"] = ""
    check("age check ok null without a reason: rejected", any("age cross check failed" in e for e in check_prices.check(d)), True)
    d = json.loads(json.dumps(nulls))
    next(s for s in d["sailings"] if s["id"].startswith("getaway"))["taxes_per_guest"] = 0
    check("taxes of $0 (not null): rejected", any("taxes_per_guest must be a positive number or null" in e for e in check_prices.check(d)), True)
    d = json.loads(json.dumps(nulls))
    del d["rates"]["open_bar"]
    check("a rate key that is gone (not null): rejected", any("rates.open_bar is missing" in e for e in check_prices.check(d)), True)

    # fetch_prices: rates. Each page read once; a page that fails keeps the previous rate (any age,
    # stale_since) or, with none, leaves the rate null with a warning.
    reads = []
    keep_page, keep_log = fp.page_text, fp.log
    fp.log = lambda m: None
    try:
        def ok_page(url):
            reads.append(url)
            return ("Prices are Per Person Per Day 1-8 (Adult) $49.99 1-2 (Child) $40 "
                    "2 - 5 Nights $32 USD 6+ Nights $28.50 USD Unlimited Soda Beverage Package is $12.50 USD per person per day "
                    "$25.00 USD per person per day for The Haven and Suites; $20.00 USD per person per day for Club Balcony Suite and below "
                    "All guests 3 years or older")
        fp.page_text = ok_page
        rates, warns = fp.fetch_rates(None)
        check("rates read from NCL's pages", (rates["free_at_sea_plus"]["adult_per_day"], rates["open_bar"]["per_day_2_to_5_nights"], rates["service_charge"]["standard_per_night"]), (49.99, 32.0, 20.0))
        check("each NCL page read once (2 calls for 3 rates)", sorted(reads), sorted([fp.TERMS_URL, fp.SERVICE_CHARGE_URL]))

        def down(url):
            reads.append(url)
            raise RuntimeError("HTTP 503")
        fp.page_text = down
        prev = {"rates": json.loads(json.dumps(rates))}
        prev["rates"]["open_bar"]["checked_at"] = "2026-01-01"
        reads.clear()
        rates2, warns2 = fp.fetch_rates(prev)
        check("pages down: previous rates kept, at any age", rates2["open_bar"]["per_day_2_to_5_nights"], 32.0)
        check("pages down: kept rate marked stale_since its date", rates2["open_bar"]["stale_since"], "2026-01-01")
        check("pages down: one warning per rate", len(warns2), 3)
        rates3, warns3 = fp.fetch_rates(None)
        check("pages down, no previous rates: all null", [rates3[k] for k in ("free_at_sea_plus", "open_bar", "service_charge")], [None, None, None])
        check("pages down, no previous rates: warnings say left empty", all(w.endswith("left empty") for w in warns3) and len(warns3) == 3, True)
        prev_null = {"rates": {"free_at_sea_plus": None, "open_bar": None, "service_charge": None}}
        check("pages down, previous rates null: still null (never guessed)", list(fp.fetch_rates(prev_null)[0].values()), [None, None, None])
    finally:
        fp.page_text, fp.log = keep_page, keep_log

    # fetch_prices: gratuities after a failed age test. Previous ones kept up to 3 days with a
    # passing age check; otherwise null with a warning naming the ship.
    cfg = next(c for c in fp.SAILINGS if c["id"].startswith("getaway"))
    grat = {"open_bar": {"title": "Unlimited Open Bar", "per_guest": 96, "soda_under_21_position_2": 37.5, "checked_at": "2026-10-13"},
            "specialty_dining": {"title": "Specialty Dining - 1 Meal", "per_guest": 20, "checked_at": "2026-10-13"}}
    prev_s = {"id": cfg["id"], "gratuities": grat}
    previous = {"saved_at": "2026-10-13T10:00:00Z", "sailings": [prev_s],
                "checks": {"ages": [{"sailing": cfg["id"], "ok": True, "expected": 1, "ncl_total": 1}]}}
    utc = lambda s: dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    fp.log = lambda m: None
    try:
        w = []
        g, age = fp.kept_gratuities(cfg, prev_s, previous, utc("2026-10-16T10:00:00Z"), RuntimeError("x"), w)
        check("age test failed: gratuities from 3 days ago kept", (g is grat, age.get("kept_from"), w), (True, "2026-10-13", []))
        w = []
        g, age = fp.kept_gratuities(cfg, prev_s, previous, utc("2026-10-17T10:00:00Z"), RuntimeError("x"), w)
        check("age test failed: gratuities from 4 days ago not used, null", (g, age["ok"]), (None, None))
        check("age test failed: warning names the ship", len(w) == 1 and w[0].startswith("Getaway:") and "gratuities" in w[0], True)
        w = []
        bad_prev = dict(previous, checks={"ages": [{"sailing": cfg["id"], "ok": None, "why": "x"}]})
        check("age test failed, previous age check didn't pass: null", fp.kept_gratuities(cfg, prev_s, bad_prev, utc("2026-10-14T10:00:00Z"), RuntimeError("x"), w)[0], None)
        w = []
        check("age test failed, no previous file: null", fp.kept_gratuities(cfg, None, None, utc("2026-10-14T10:00:00Z"), RuntimeError("x"), w)[0], None)
    finally:
        fp.log = keep_log


# Availability answer shape with NCL's Kids Sail Free offer, as the Joy page saw it on 2026-10-13
# (codes and words only; no NCL call).
KSF_ANSWER = {"offerGroups": [
    {"code": "FREE-AT-SEA", "promotionsInGroup": [{"isDefaultInGroup": True, "promotion": {
        "promotionCodes": ["ALL4CHO"], "stateroomTypes": ["INSIDE", "BALCONY"], "offers": [{"code": "Free-At-Sea", "title": "Free at Sea"}]}}]},
    {"code": "MORE-OFFERS", "promotionsInGroup": [{"promotion": {
        "promotionCodes": ["34CHO"], "stateroomTypes": ["INSIDE", "OCEANVIEW", "BALCONY", "MINISUITE"],
        "offers": [{"code": "Kids-Sail-Free-Offer", "title": "Kids Sail Free", "shortDescription": "3rd & 4th guests sail free",
                    "description": "3rd and 4th guests sailing in the same stateroom sail for taxes, fees, and port expenses only"}]}}]}]}


def test_kids_sail_free():
    import check_prices
    k = fp.kids_sail_free(KSF_ANSWER)
    check("Kids Sail Free read from offerGroups", (k["title"], k["codes"], k["types"]), ("Kids Sail Free", ["34CHO"], ["INSIDE", "OCEANVIEW", "BALCONY", "MINISUITE"]))
    check("Kids Sail Free not listed: None", fp.kids_sail_free({"offerGroups": KSF_ANSWER["offerGroups"][:1]}), None)
    check("Kids Sail Free by title only", fp.kids_sail_free({"offerGroups": [{"promotionsInGroup": [{"promotion": {"offers": [{"title": "KIDS SAIL FREE"}]}}]}]})["types"], [])
    check("Kids Sail Free: the Free at Sea code is still read the same way", fp.default_fare_codes(KSF_ANSWER), {"INSIDE": "ALL4CHO", "BALCONY": "ALL4CHO"})
    with open(os.path.join(os.path.dirname(TOOLS), "data", "prices.json"), encoding="utf-8") as f:
        real = schema5(json.load(f))
    check("format check: kids_sail_free null passes", check_prices.check(real), [])
    d = json.loads(json.dumps(real))
    d["sailings"][0]["kids_sail_free"] = dict(k, checked_at="2026-10-15T10:20:00Z")
    check("format check: kids_sail_free from NCL passes", check_prices.check(d), [])
    for bad in ({"title": "", "types": []}, {"title": "Kids Sail Free"}, {"title": "Kids Sail Free", "types": "INSIDE"}, "yes"):
        d["sailings"][0]["kids_sail_free"] = bad
        check(f"format check: kids_sail_free {bad!r} rejected", any("kids_sail_free must be null" in e for e in check_prices.check(d)), True)
    del d["sailings"][0]["kids_sail_free"]
    check("format check: kids_sail_free missing from a schema 5 file rejected", any("kids_sail_free is missing" in e for e in check_prices.check(d)), True)


# ---------- Florida resident rates (5.1.0) ----------

def fl_entry(off, at="2026-10-27T20:41:00Z", web=300.0, typ="BALCONY"):
    return {"type": typ, "website_fare_pp": web, "florida_fare_pp": round(web - off, 2), "off_pp": off,
            "checked_at": at, "source": "logged-in NCL account"}


def fl_file(check="light", on="2026-10-27", cats=None, missing=None, saved="2026-10-27T20:45:00Z"):
    cats = cats if cats is not None else {"getaway-2027-06-11": {"BF": fl_entry(0)}, "aura-2027-06-14": {"BF": fl_entry(0)}}
    return {"schema_version": 1, "saved_at": saved, "guests": 2, "source": "test", "check": check, "checked_on": on,
            "sailings": {sid: {"package_id": "123", "categories": c, "missing": (missing or {}).get(sid, [])} for sid, c in cats.items()}}


def test_florida_plan_and_format():
    import check_florida
    import fetch_florida as ff
    d = dt.date
    check("Florida plan: no previous file -> light check", ff.plan(None, d(2026, 10, 27))[0], "light")
    light = fl_file()
    check("Florida plan: light check 6 days ago, no discount -> nothing due", ff.plan(light, d(2026, 11, 2))[0], None)
    check("Florida plan: light check 7 days ago -> light check", ff.plan(light, d(2026, 11, 3))[0], "light")
    found = fl_file(cats={"getaway-2027-06-11": {"MB": fl_entry(60, typ="MINISUITE")}, "aura-2027-06-14": {"BF": fl_entry(0)}})
    check("Florida plan: light check found a discount -> full check (same day)", ff.plan(found, d(2026, 10, 27))[0], "full")
    full_found = dict(found, check="full")
    check("Florida plan: full check with a discount, 6 days ago -> nothing due", ff.plan(full_found, d(2026, 11, 2))[0], None)
    check("Florida plan: full check with a discount, 7 days ago -> full check again", ff.plan(full_found, d(2026, 11, 3))[0], "full")
    full_none = fl_file(check="full")
    check("Florida plan: full check found no discount, 7 days ago -> back to a light check", ff.plan(full_none, d(2026, 11, 3))[0], "light")
    part = fl_file(check="full", missing={"aura-2027-06-14": ["B4"]})
    check("Florida plan: full check with failed cabins, same day -> retry", ff.plan(part, d(2026, 10, 27))[0], "retry")
    check("Florida plan: full check with failed cabins, next day -> retry", ff.plan(part, d(2026, 10, 28))[0], "retry")
    check("Florida plan: full check with failed cabins, 2 days later -> nothing due", ff.plan(part, d(2026, 10, 29))[0], None)
    check("Florida plan: an unreadable previous file -> light check", ff.plan({"schema_version": 1}, d(2026, 10, 27))[0], "light")
    check("Florida: $0.50 off is not a discount (rounding, seen on Joy's IX)",
          ff.has_discount(fl_file(cats={"getaway-2027-06-11": {"IF": fl_entry(0.5)}})), False)
    check("Florida: $1 off is a discount", ff.has_discount(fl_file(cats={"getaway-2027-06-11": {"IF": fl_entry(1)}})), True)
    check("Florida: a Florida fare above the website fare is not a discount",
          ff.has_discount(fl_file(cats={"getaway-2027-06-11": {"IF": fl_entry(-20)}})), False)
    # Eastern dates: 8:30 PM Eastern on Nov 1 (after daylight saving time ends) is Nov 2 by UTC date.
    check("Florida: Eastern date of 2026-11-02T01:30:00Z", ff.eastern_date("2026-11-02T01:30:00Z"), d(2026, 11, 1))
    check("Florida: Eastern date of 2026-10-28T03:30:00Z (EDT)", ff.eastern_date("2026-10-28T03:30:00Z"), d(2026, 10, 27))

    # Format check: numbers, codes and dates only.
    check("check_florida: a light check file passes", check_florida.check(light), [])
    check("check_florida: a full check with missing cabins passes", check_florida.check(part), [])
    bad = fl_file()
    bad["email"] = "someone@example.com"
    check("check_florida: an extra top-level key fails", any("unexpected keys ['email']" in e for e in check_florida.check(bad)), True)
    bad = fl_file()
    bad["sailings"]["aura-2027-06-14"]["categories"]["BF"]["name"] = "x"
    check("check_florida: an extra category key fails", any("unexpected keys ['name']" in e for e in check_florida.check(bad)), True)
    bad = fl_file()
    bad["sailings"]["aura-2027-06-14"]["categories"]["BF"]["off_pp"] = 5
    check("check_florida: off_pp that isn't website minus Florida fails", any("off_pp must be" in e for e in check_florida.check(bad)), True)
    bad = fl_file(cats={"joy-2026-11-20": {"BF": fl_entry(0)}})
    check("check_florida: an unknown sailing fails", any("id must be one of" in e for e in check_florida.check(bad)), True)
    bad = fl_file(missing={"aura-2027-06-14": ["B4"]})
    check("check_florida: missing cabins in a light check fail", any("only used by a full check" in e for e in check_florida.check(bad)), True)
    bad = fl_file(cats={"aura-2027-06-14": {"BF": fl_entry(0, at="2026-10-20T15:00:00Z")}})
    check("check_florida: an entry from before checked_on fails", any("before checked_on" in e for e in check_florida.check(bad)), True)
    bad = fl_file(cats={"aura-2027-06-14": {"BF": dict(fl_entry(0), source="screenshot")}})
    check("check_florida: a source other than the signed-in account fails", any("source must be" in e for e in check_florida.check(bad)), True)
    check("check_florida: no categories at all fails", any("no category" in e for e in check_florida.check(fl_file(cats={"aura-2027-06-14": {}}))), True)

    # The fare reading: the saved Getaway B4 answer for 2 guests lists $299 per guest (STATEROOM line).
    check("Florida fare_pp on a saved 2 guest price summary = NCL's $299 per guest",
          ff.fare_pp(saved("price_summary_getaway_B4_2_browser_2026-10-06")), 299.0)


# A stand-in for NCL: availability, anonymous price summaries (website fares) and the signed-in
# browser page (Florida fares), counting every call.
FAKE_CATS = {   # type: [(code, price at 2 guests, guarantee)]
    "STUDIO": [("T1", 900, False)],
    "INSIDE": [("IX", 380, True), ("IF", 398, False), ("IA", 420, False)],
    "OCEANVIEW": [("OF", 500, False)],
    "BALCONY": [("BX", 560, True), ("BF", 578, False), ("B4", 600, False), ("BT", 700, False)],
    "MINISUITE": [("MB", 678, False)],
    "SUITE": [("SC", 2000, False)],
    "HAVEN": [("H5", 3000, False), ("H6", 3500, False)],
}


def fake_availability():
    types = []
    for tc, cats in FAKE_CATS.items():
        types.append({"code": tc, "stateroomsPricing": [{"stateroom": {"title": "Solo Balcony" if code == "BT" else "x"},
                      "categoryPricing": [{"isAvailable": True, "standardOption": {"pricedCategoryCode": code, "price": price, "isGTY": gty}}]}
                      for code, price, gty in cats]})
    groups = [{"code": "FREE-AT-SEA", "promotionsInGroup": [
        {"isDefaultInGroup": True, "promotion": {"promotionCodes": ["ALL4CHO"], "stateroomTypes": ["INSIDE", "OCEANVIEW", "BALCONY", "MINISUITE"]}},
        {"isDefaultInGroup": True, "promotion": {"promotionCodes": ["CHOALL4M"], "stateroomTypes": ["SUITE", "HAVEN"]}}]}]
    return {"stateroomTypesPricing": types, "offerGroups": groups}


def fake_summary(fare_pp, extra=None):
    res = {"staterooms": [{"paymentOptions": [{"paymentType": "HOLD"}], "pricing": {"priceGroups": [
        {"code": "FREE-AT-SEA", "priceItems": [{"code": "unlimited-open-bar-offer", "guests": [{"price": 96}, {"price": 96}]}]},
        {"code": "TAXES-AND-FEES", "priceItems": [{"code": "taxes-and-fees", "guests": [{"price": 100}, {"price": 100}]}]}]}}],
        "total": {"subtotal": 2 * fare_pp + 192, "taxesAndFees": 200, "grandTotal": 2 * fare_pp + 392}}
    res.update(extra or {})
    return res


class FloridaNCL:
    def __init__(self, florida_off=None, fail=(), hold=False):
        self.florida_off = florida_off or {}   # (ship_short, code): dollars off per guest
        self.fail, self.hold = set(fail), hold
        self.calls = {"availability": 0, "website": 0, "florida": 0}
        self.ship = {}

    def availability(self, cfg, guests):
        self.calls["availability"] += 1
        self.ship[cfg["package_id"]] = cfg["ship_short"]
        return fake_availability()

    def fare(self, b):
        code = b["stateroomFilters"][0]["pricedCategoryCode"]
        return code, self.ship[b["packageId"]], next(p for cats in FAKE_CATS.values() for c, p, g in cats if c == code) / 2

    def request(self, url, b=None, **kw):
        assert url == fp.PRICE_SUMMARY_URL, url
        self.calls["website"] += 1
        code, ship, fare = self.fare(b)
        if code in self.fail:
            raise RuntimeError("NCL answered HTTP 500")
        return fake_summary(fare)

    def evaluate(self, script, arg):
        self.calls["florida"] += 1
        code, ship, fare = self.fare(arg["body"])
        if self.hold:
            return {"status": 200, "text": json.dumps(fake_summary(fare, {"heldUntil": "2027-01-01T00:00:00Z"}))}
        return {"status": 200, "text": json.dumps(fake_summary(fare - self.florida_off.get((ship, code), 0)))}

    # browser context
    def cookies(self, url):
        import base64
        from urllib.parse import quote
        payload = base64.urlsafe_b64encode(json.dumps({"exp": 4102444800}).encode()).decode().rstrip("=")
        return [{"name": "NCLAuth", "value": quote(json.dumps({"accessToken": f"x.{payload}.y"}))}]

    def goto(self, url, **kw):
        pass

    def close(self):
        pass

    stop = close


def florida_run(folder, ncl, when):
    """One fetch_florida run (no --push) in a temporary copy of the repo with the stand-in for NCL."""
    import fetch_florida as ff
    saved_state = (ff.ROOT, ff.PRICES, ff.OUT, ff.open_browser, ff.profile_busy, ff.now_utc, ff.log, fp.fetch_availability, fp.request, fp.PAUSE_SECONDS)
    ff.ROOT, ff.PRICES, ff.OUT = folder, os.path.join(folder, "data", "prices.json"), os.path.join(folder, "data", "florida.json")
    ff.open_browser = lambda profile, show: (ncl, ncl, ncl)
    ff.profile_busy = lambda profile: None
    ff.now_utc = lambda: dt.datetime.strptime(when, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    fp.fetch_availability, fp.request, fp.PAUSE_SECONDS = ncl.availability, ncl.request, 0
    ff.log = lambda m: None
    for k in ff.calls:
        ff.calls[k] = 0
    try:
        return ff.run(os.path.join(folder, "profile"), False, False)
    finally:
        ff.ROOT, ff.PRICES, ff.OUT, ff.open_browser, ff.profile_busy, ff.now_utc, ff.log, fp.fetch_availability, fp.request, fp.PAUSE_SECONDS = saved_state


def test_florida_runs():
    import check_florida
    import fetch_florida as ff
    folder = tempfile.mkdtemp(prefix="june-florida-")
    os.makedirs(os.path.join(folder, "data"))
    with open(os.path.join(os.path.dirname(TOOLS), "data", "prices.json"), encoding="utf-8") as f:
        prices = json.load(f)
    with open(os.path.join(folder, "data", "prices.json"), "w", encoding="utf-8") as f:
        json.dump(prices, f)
    out = os.path.join(folder, "data", "florida.json")
    read = lambda: json.load(open(out, encoding="utf-8")) if os.path.exists(out) else None
    per_ship = sum(len(v) for k, v in FAKE_CATS.items() if k != "STUDIO") - 1   # BT is a solo cabin
    G, A = "getaway-2027-06-11", "aura-2027-06-14"

    ncl = FloridaNCL()
    rc = florida_run(folder, ncl, "2026-10-27T13:00:00Z")
    d = read()
    check("Florida run 1 (no file): light check, exit 0", rc, 0)
    check("Florida run 1: 22 NCL calls (2 availability, 10 website, 10 signed in)", ncl.calls, {"availability": 2, "website": 10, "florida": 10})
    check("Florida run 1: the light cabins are the cheapest non-Guarantee Inside, Oceanview, Balcony, Club Balcony Suite, Haven",
          sorted(d["sailings"][G]["categories"]), ["BF", "H5", "IF", "MB", "OF"])
    check("Florida run 1: file says light check on Oct 27, no discount, passes its format check",
          (d["check"], d["checked_on"], ff.has_discount(d), check_florida.check(d)), ("light", "2026-10-27", False, []))

    ncl = FloridaNCL()
    rc = florida_run(folder, ncl, "2026-10-27T21:00:00Z")
    check("Florida run 2 (same Eastern day): nothing due, 0 NCL calls", (rc, ncl.calls), (0, {"availability": 0, "website": 0, "florida": 0}))
    ncl = FloridaNCL()
    florida_run(folder, ncl, "2026-11-03T01:30:00Z")   # 9:30 PM Eastern on Nov 2: 6 Eastern days
    check("Florida run 3 (Nov 2, 9:30 PM Eastern, Nov 3 by UTC date): nothing due, 0 NCL calls", ncl.calls, {"availability": 0, "website": 0, "florida": 0})

    # A week later NCL offers $60 off the Getaway's MB and $25 off the Aura's B4 (not a light cabin).
    ncl = FloridaNCL(florida_off={("Getaway", "MB"): 60, ("Aura", "B4"): 25})
    rc = florida_run(folder, ncl, "2026-11-03T14:00:00Z")
    d = read()
    full_calls = 2 * per_ship
    check("Florida run 4 (light finds a discount): full check the same run, exit 0", rc, 0)
    check(f"Florida run 4: {2 + 2 * full_calls} NCL calls (every cabin once, the light cabins not asked again)",
          ncl.calls, {"availability": 2, "website": full_calls, "florida": full_calls})
    check("Florida run 4: file says full check on Nov 3 with every cabin of both ships",
          (d["check"], d["checked_on"], len(d["sailings"][G]["categories"]), len(d["sailings"][A]["categories"])), ("full", "2026-11-03", per_ship, per_ship))
    check("Florida run 4: each cabin's own amount (Getaway MB $60, Aura B4 $25, Aura MB $0)",
          (d["sailings"][G]["categories"]["MB"]["off_pp"], d["sailings"][A]["categories"]["B4"]["off_pp"], d["sailings"][A]["categories"]["MB"]["off_pp"]), (60, 25, 0))
    check("Florida run 4: Studio and solo cabins left out", any(c in d["sailings"][G]["categories"] for c in ("T1", "BT")), False)
    check("Florida run 4: passes its format check", check_florida.check(d), [])

    ncl = FloridaNCL(florida_off={("Getaway", "MB"): 60})
    florida_run(folder, ncl, "2026-11-09T14:00:00Z")
    check("Florida run 5 (6 days into an active discount): nothing due", ncl.calls["availability"], 0)
    # Next week the discount is gone; one Aura cabin fails.
    ncl = FloridaNCL(fail={"SC"})
    rc = florida_run(folder, ncl, "2026-11-10T14:00:00Z")
    d = read()
    check("Florida run 6 (discount active, 7 days): full check again", (rc, d["check"], d["checked_on"]), (0, "full", "2026-11-10"))
    check("Florida run 6: the failed cabin is listed as missing on both ships", (d["sailings"][G]["missing"], d["sailings"][A]["missing"]), (["SC"], ["SC"]))
    check("Florida run 6: no discount any more", ff.has_discount(d), False)
    ncl = FloridaNCL()
    rc = florida_run(folder, ncl, "2026-11-10T18:00:00Z")
    d = read()
    check("Florida run 7 (same day): retries only the failed cabins (2 availability, 2 + 2 price summaries)",
          ncl.calls, {"availability": 2, "website": 2, "florida": 2})
    check("Florida run 7: nothing missing, every cabin kept, checked_on unchanged",
          (d["sailings"][A]["missing"], len(d["sailings"][A]["categories"]), d["checked_on"]), ([], per_ship, "2026-11-10"))
    # A failed cabin that is no longer for sale: the retry clears the list with no signed-in call.
    d["sailings"][A]["missing"] = ["ZZ"]
    d["check"] = "full"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(d, f)
    ncl = FloridaNCL()
    rc = florida_run(folder, ncl, "2026-11-11T14:00:00Z")
    d = read()
    check("Florida retry, the failed cabin is gone: 1 availability call, no price calls, list cleared",
          (rc, ncl.calls, d["sailings"][A]["missing"], d["checked_on"]), (0, {"availability": 1, "website": 0, "florida": 0}, [], "2026-11-10"))
    ncl = FloridaNCL()
    florida_run(folder, ncl, "2026-11-17T14:00:00Z")
    d = read()
    check("Florida run 8 (full check found no discount, 7 days): back to a light check",
          (d["check"], ncl.calls), ("light", {"availability": 2, "website": 10, "florida": 10}))

    # A light check with a failed cabin and no discount: file not changed, retried next run.
    before = read()
    ncl = FloridaNCL(fail={"OF"})
    rc = florida_run(folder, ncl, "2026-11-24T14:00:00Z")
    check("Florida run 9 (a light cabin fails, no discount): exit 4, file not changed", (rc, read() == before), (4, True))

    # A hold signal in a signed-in answer stops the run; the file is not changed.
    ncl = FloridaNCL(hold=True)
    try:
        florida_run(folder, ncl, "2026-11-24T18:00:00Z")
        stopped = False
    except fp.HoldSignal:
        stopped = True
    check("Florida: a hold signal in a signed-in answer stops the run (1 signed-in call)", (stopped, ncl.calls["florida"]), (True, 1))
    check("Florida: after the hold signal the file is not changed", read() == before, True)

    ncl = FloridaNCL()
    rc = florida_run(folder, ncl, "2027-06-11T12:00:00Z")
    check("Florida: from Jun 11, 2027 (Eastern) nothing runs, 0 NCL calls", (rc, ncl.calls["availability"] + ncl.calls["website"]), (0, 0))

    # The signed-in call's own guards.
    ncl = FloridaNCL()
    try:
        ff.signed_in_post(ncl, "https://www.ncl.com/api/vacation-builder/cabin/manage-cabin", {})
        refused = False
    except RuntimeError:
        refused = True
    check("Florida: signed-in call refuses a manage-cabin address before calling", (refused, ncl.calls["florida"]), (True, 0))
    page = type("P", (), {"evaluate": lambda self, s, a: {"status": 200, "text": json.dumps(saved("manage_cabin_REAL_HOLD_2026-10-06"))}})()
    try:
        ff.signed_in_post(page, fp.PRICE_SUMMARY_URL, {})
        stopped = False
    except fp.HoldSignal:
        stopped = True
    check("Florida: the saved real hold answer stops a signed-in call", stopped, True)
    page = type("P", (), {"evaluate": lambda self, s, a: {"status": 200, "text": json.dumps(saved("price_summary_getaway_B4_2_browser_2026-10-06"))}})()
    check("Florida: a saved price summary with the HOLD payment option passes", ff.fare_pp(ff.signed_in_post(page, fp.PRICE_SUMMARY_URL, {})), 299.0)


def test_florida_clone_guard():
    """--push refuses to commit unless the clone's Git email is the noreply address and it is on main."""
    import fetch_florida as ff
    folder = tempfile.mkdtemp(prefix="june-florida-git-")
    run = lambda *a: subprocess.run(["git", "-C", folder, *a], capture_output=True, text=True)
    run("init", "-q", "-b", "main")
    run("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "--allow-empty", "-m", "start")
    old = ff.ROOT, ff.log
    ff.ROOT, ff.log = folder, (lambda m: None)
    try:
        run("config", "user.email", "someone@example.com")
        check("Florida --push: a personal Git email is refused (exit 7)", (ff.clone_ok() or [None])[0], 7)
        check("Florida --push: publish() refuses too", ff.publish("light"), 7)
        run("config", "user.email", "x174554998+DASatizabal@users.noreply.github.com")
        check("Florida --push: only the exact noreply address passes", (ff.clone_ok() or [None])[0], 7)
        run("config", "user.email", ff.NOREPLY)
        run("switch", "-q", "-c", "june-joy-upgrades")
        check("Florida --push: a branch other than main is refused (exit 8)", (ff.clone_ok() or [None])[0], 8)
        run("switch", "-q", "main")
        check("Florida --push: noreply email on main passes", ff.clone_ok(), None)
    finally:
        ff.ROOT, ff.log = old


def offers_page(banner_text=None, title="Limited-Time Offer: DoubleUp!", terms=True):
    """A small stand-in for NCL's CruiseNext page."""
    parts = ['<h2 class="cmp-title__text">How It works</h2><div class="cmp-text"><p>Buy credits on board.</p></div>']
    if banner_text is not None:
        parts.append(f'<h3 class="cmp-title__text">{title}</h3><div class="cmp-text"><div><p>{banner_text}</p></div></div>')
    if terms:
        parts.append("<p><sub>*CruiseNext Credits can only be applied to new reservations. Only one CNC or CNHC "
                     "can be applied per stateroom.</sub></p>")
    return "<html><body>" + "".join(parts) + "</body></html>"


def test_offers():
    """CruiseNext offer watch (5.2.0, any multi-credit offer and schema 2 since 5.3.0):
    tools/fetch_offers.py reads the banner, one issue per change, and tools/check_offers.py. NCL's
    real markup and stand-in pages; no NCL calls."""
    import check_offers as co
    import fetch_offers as fo
    day = lambda d, h=10: dt.datetime(2026, 10, d, h, 21, tzinfo=dt.timezone.utc)
    nov = lambda d, h=10: dt.datetime(2026, 11, d, h, 21, tzinfo=dt.timezone.utc)
    with open(os.path.join(TEST_DATA, "cruisenext_doubleup.html"), encoding="utf-8") as f:
        real = f.read()
    with open(os.path.join(TEST_DATA, "cruisenext_tripleup.html"), encoding="utf-8") as f:
        real3 = f.read()
    now_text = ("Book a Balcony and above stateroom on any sailing at least 90 days prior to sailing and apply TWO "
                "CruiseNext, CruiseNext Haven, CruiseNext Lite credits.*")
    three_text = now_text.replace("TWO", "THREE")

    # First run on NCL's real markup (saved 2026-10-28): the "watch started" issue.
    first = fo.build(real, None, day(29))
    du = first["multi_credit"]
    check("Offer: schema 2", first["schema_version"], 2)
    check("Offer: banner read from NCL's real markup", (du["listed"], du["title"], du["name"], du["credits"], du["text"]),
          (True, "Limited-Time Offer: DoubleUp!", "DoubleUp!", 2, now_text))
    check("Offer: Balcony and above", du["types"], ["BALCONY", "MINISUITE", "SUITE", "HAVEN"])
    check("Offer: 90 days before sailing", (du["min_days"], du["min_months"]), (90, None))
    check("Offer: first run is a started change, not yet reported",
          (first["last_change"]["kind"], first["last_change"]["reported"], first["last_change"]["old_listed"]),
          ("started", False, None))
    check("Offer: first file passes the format check (schema 2 only)", co.check(first, any_schema=False), [])
    title, body, marker = fo.issue(first)
    check("Offer: started issue title", title, "CruiseNext offer watch started (Oct 29, 2026)")
    check("Offer: issue mentions the owner, the link, the new text and credits",
          ["@DASatizabal" in body, fo.CRUISENEXT_URL in body, now_text in body, marker in body, "New credits: 2" in body], [True] * 5)
    check("Offer: issue text has no em dash", EM_DASH in title + body, False)

    # Not reported yet (the issue couldn't be opened): the next day tries again with the same marker.
    retry = fo.build(real, first, day(30))
    check("Offer: an unreported change is tried again with the same marker",
          (fo.issue(retry) or (None, None, None))[2], marker)
    check("Offer: state date kept while nothing changes", retry["multi_credit"]["since"], "2026-10-29")

    # Reported: the next days open nothing.
    first["last_change"]["reported"] = True
    same = fo.build(real, first, day(30))
    check("Offer: same text the next day opens no issue", fo.issue(same), None)
    check("Offer: same text keeps the last change as it was", same["last_change"], first["last_change"])
    check("Offer: read_on moves to today", same["multi_credit"]["read_on"], "2026-10-30")
    check("Offer: same-day file passes", co.check(same, any_schema=False), [])

    # TripleUp on NCL's real markup (saved 2026-11-07): a "changed" issue, DoubleUp to TripleUp.
    trip = fo.build(real3, same, nov(7))
    t = trip["multi_credit"]
    check("Offer: TripleUp read from NCL's real markup", (t["listed"], t["name"], t["credits"], t["text"], t["types"], t["min_days"]),
          (True, "TripleUp!", 3, three_text, ["BALCONY", "MINISUITE", "SUITE", "HAVEN"], 90))
    ch = trip["last_change"]
    check("Offer: DoubleUp to TripleUp is a changed change with both names and credits",
          (ch["kind"], ch["old_name"], ch["old_credits"], ch["new_name"], ch["new_credits"]), ("changed", "DoubleUp!", 2, "TripleUp!", 3))
    check("Offer: TripleUp file passes", co.check(trip, any_schema=False), [])
    t_title, t_body, _ = fo.issue(trip)
    check("Offer: changed issue title names both offers", t_title, "CruiseNext offer changed: DoubleUp to TripleUp (Nov 7, 2026)")
    check("Offer: changed issue shows old and new text and credits",
          [f'Old: DoubleUp!: "{now_text}"' in t_body, "Old credits: 2" in t_body, f'New: TripleUp!: "{three_text}"' in t_body,
           "New credits: 3" in t_body, "up to 3 CruiseNext credits per booking (TripleUp)" in t_body], [True] * 5)
    trip["last_change"]["reported"] = True
    # Same name, another number in both heading and text is impossible (the name gives the number);
    # the same name with new wording is a text change.
    reworded = fo.build(offers_page(three_text.replace("any sailing", "all sailings"), "Limited-Time Offer: TripleUp!"), trip, nov(8))
    check("Offer: TripleUp with new wording is a text change", fo.issue(reworded)[0], "CruiseNext offer text changed: TripleUp (Nov 8, 2026)")

    # Headings with or without "!", spaces or hyphens, and the number in words or digits.
    for heading, text, want in [("Limited-Time Offer: Double Up", now_text, ("Double Up", 2)),
                                ("Limited-Time Offer: Triple-Up!", three_text, ("Triple-Up!", 3)),
                                ("QuadUp!", now_text.replace("TWO", "FOUR"), ("QuadUp!", 4)),
                                ("Quadruple Up!", now_text.replace("TWO", "4"), ("Quadruple Up!", 4)),
                                ("TRIPLEUP", now_text.replace("TWO", "three"), ("TRIPLEUP", 3))]:
        got = fo.build(offers_page(text, heading), same, day(31))
        check(f"Offer: heading {heading!r}", (got["multi_credit"]["name"], got["multi_credit"]["credits"], got["warnings"]), want + ([],))
        check(f"Offer: heading {heading!r} passes", co.check(got, any_schema=False), [])

    # The heading and the text disagree, or the number can't be read: null credits, a warning, one credit.
    for name, heading, text in [("heading TripleUp, text TWO", "Limited-Time Offer: TripleUp!", now_text),
                                ("no number in the text", "Limited-Time Offer: TripleUp!",
                                 "Book a Balcony and above stateroom on any sailing at least 90 days prior to sailing and apply extra CruiseNext credits.")]:
        got = fo.build(offers_page(text, heading), same, day(31))
        m = got["multi_credit"]
        check(f"Offer: {name}: credits null with a warning", (m["listed"], m["credits"], len(got["warnings"]), "one credit" in got["warnings"][0]),
              (True, None, 1, True))
        check(f"Offer: {name}: passes the format check", co.check(got, any_schema=False), [])
        check(f"Offer: {name}: the issue says one credit", "one CruiseNext credit per booking" in fo.issue(got)[1], True)

    # The banner ends, changes, comes back: one issue each, each with its own marker.
    ended = fo.build(offers_page(None), same, day(31))
    check("Offer: banner gone is an ended change", (ended["last_change"]["kind"], ended["multi_credit"]["listed"]), ("ended", False))
    check("Offer: ended file passes", co.check(ended, any_schema=False), [])
    e_title, e_body, e_marker = fo.issue(ended)
    check("Offer: ended issue title and texts", (e_title, "(no multi-credit offer on the page)" in e_body, now_text in e_body),
          ("CruiseNext offer ended: DoubleUp (Oct 31, 2026)", True, True))
    ended["last_change"]["reported"] = True
    back = fo.build(offers_page(now_text), ended, day(31, 20))
    check("Offer: banner back is an appeared change", (back["last_change"]["kind"], fo.issue(back)[0]),
          ("appeared", "CruiseNext offer appeared: DoubleUp (Oct 31, 2026)"))
    check("Offer: every change has its own marker",
          len({marker, e_marker, back["last_change"]["marker"]}), 3)
    back["last_change"]["reported"] = True
    new_text = "Book ANY stateroom on any sailing booked at least 6 months in advance and apply TWO CruiseNext credits."
    changed = fo.build(offers_page(new_text), back, dt.datetime(2026, 11, 2, 14, tzinfo=dt.timezone.utc))
    check("Offer: new text is a changed change", (changed["last_change"]["kind"], fo.issue(changed)[0]),
          ("changed", "CruiseNext offer text changed: DoubleUp (Nov 2, 2026)"))
    check("Offer: any stateroom, 6 months", (changed["multi_credit"]["types"], changed["multi_credit"]["min_days"], changed["multi_credit"]["min_months"]),
          (fo.TYPE_ORDER, None, 6))
    check("Offer: changed file passes", co.check(changed, any_schema=False), [])
    c_body = fo.issue(changed)[1]
    check("Offer: changed issue shows old and new text", (f'Old: DoubleUp!: "{now_text}"' in c_body, f'New: DoubleUp!: "{new_text}"' in c_body), (True, True))
    check("Offer: Eastern date, not UTC (Nov 2 at 3:30 AM UTC is Nov 1, 10:30 PM in Miami)",
          fo.build(offers_page(None), back, dt.datetime(2026, 11, 2, 3, 30, tzinfo=dt.timezone.utc))["checked_on"], "2026-11-01")
    check("Offer: evening run belongs to the Eastern day",
          fo.build(offers_page(None), back, dt.datetime(2026, 11, 3, 2, 0, tzinfo=dt.timezone.utc))["checked_on"], "2026-11-02")

    # Pages that can't be read keep the previous state, warn, and open nothing.
    for name, page, error in [("a page without CruiseNext terms", offers_page(now_text, terms=False), None),
                              ("an error loading the page", None, "RuntimeError: NCL answered HTTP 403"),
                              ("a multi-credit heading with no text", offers_page("").replace("<p></p>", ""), None),
                              ("offer text far from the heading", offers_page(now_text).replace(
                                  "</h3>", "</h3><div>" + " " * (fo.NEAR + 10) + "</div>"), None),
                              ("THREE credits under an unknown heading", offers_page(three_text, "Limited-Time Offer: TrioBonus!"), None)]:
        kept = fo.build(page, same, day(31), page_error=error)
        check(f"Offer: {name} keeps the state", (kept["read_ok"], kept["multi_credit"], kept["last_change"]),
              (False, same["multi_credit"], same["last_change"]))
        check(f"Offer: {name} opens no issue and warns", (fo.issue(kept), len(kept["warnings"])), (None, 1))
        check(f"Offer: {name} passes the format check", co.check(kept, any_schema=False), [])
    other = fo.build(offers_page("Book any stateroom and apply ONE CruiseNext credit.", "Limited-Time Offer: Bonus!"), same, day(31))
    check("Offer: an unknown heading with one credit is no multi-credit offer (ended)", (other["read_ok"], other["last_change"]["kind"]), (True, "ended"))
    none_yet = fo.build(None, None, day(29), page_error="URLError: timed out")
    check("Offer: no previous file and no page: nothing read yet, no issue", (none_yet["multi_credit"], fo.issue(none_yet)), (None, None))
    check("Offer: nothing read yet passes", co.check(none_yet, any_schema=False), [])

    # Wording that can't be read: saved as null with a warning, never guessed.
    odd = fo.build(offers_page("Book something special stateroom and apply TWO CruiseNext credits."), same, day(31))
    check("Offer: unknown wording gives null types and lead time",
          (odd["multi_credit"]["types"], odd["multi_credit"]["min_days"], odd["multi_credit"]["min_months"], len(odd["warnings"])), (None, None, None, 2))
    check("Offer: unknown wording passes the format check", co.check(odd, any_schema=False), [])
    check("Offer: unknown wording means one credit", "one CruiseNext credit" in fo.issue(odd)[1], True)
    for text, want in [("Book a Club Balcony Suite and above stateroom", ["MINISUITE", "SUITE", "HAVEN"]),
                       ("Book a Balcony, Club Balcony Suite or Suite stateroom", ["BALCONY", "MINISUITE", "SUITE"]),
                       ("Book a Suite or The Haven stateroom", ["SUITE", "HAVEN"]),
                       ("Book a ANY stateroom", fo.TYPE_ORDER),
                       ("Apply two credits", None)]:
        check(f"Offer types: {text}", fo.read_types(text), want)
    check("Offer: 120 days before sailing", fo.read_lead_time("at least 120 days before sailing"), (120, None))

    # Schema 1 (5.2.0) previous files: read, written back as schema 2, same state is no change.
    s1 = {"schema_version": 1, "saved_at": "2026-10-30T10:21:00Z", "checked_on": "2026-10-30", "source": fo.CRUISENEXT_URL,
          "read_ok": True, "warnings": [],
          "doubleup": {"listed": True, "title": "Limited-Time Offer: DoubleUp!", "text": now_text, "types": ["BALCONY", "MINISUITE", "SUITE", "HAVEN"],
                       "min_days": 90, "min_months": None, "read_on": "2026-10-30", "since": "2026-10-29"},
          "last_change": {"kind": "started", "on": "2026-10-29", "old_listed": None, "old_text": None, "new_listed": True,
                          "new_text": now_text, "marker": "doubleup-0123456789ab", "reported": True}}
    check("Offer: a schema 1 file passes the release check's format check", co.check(s1), [])
    check("Offer: a schema 1 file is refused as a new file", bool(co.check(s1, any_schema=False)), True)
    from1 = fo.build(real, s1, day(31))
    check("Offer: schema 1 with the same DoubleUp: no change, written as schema 2",
          (from1["schema_version"], fo.issue(from1), from1["multi_credit"]["since"], from1["last_change"]["marker"], from1["last_change"]["new_credits"]),
          (2, None, "2026-10-29", "doubleup-0123456789ab", 2))
    check("Offer: schema 1 carried over passes", co.check(from1, any_schema=False), [])
    kept1 = fo.build(None, s1, day(31), page_error="URLError: timed out")
    check("Offer: schema 1 kept on an unreadable page passes", (kept1["read_ok"], co.check(kept1, any_schema=False)), (False, []))

    # The one-time fix (5.3.0): exactly main's 2026-11-06 schema 1 file, then a multi-credit offer.
    wrong = {"schema_version": 1, "saved_at": "2026-11-06T10:20:57Z", "checked_on": "2026-11-06", "source": fo.CRUISENEXT_URL,
             "read_ok": True, "warnings": [],
             "doubleup": {"listed": False, "title": None, "text": None, "types": None, "min_days": None, "min_months": None,
                          "read_on": "2026-11-06", "since": "2026-11-06"},
             "last_change": {"kind": "ended", "on": "2026-11-06", "old_listed": True, "old_text": now_text, "new_listed": False,
                             "new_text": None, "marker": "doubleup-04e33a276287", "reported": True}}
    fixed = fo.build(real3, wrong, nov(7))
    check("Offer fix: main's 2026-11-06 'ended' then TripleUp is DoubleUp to TripleUp",
          (fixed["last_change"]["kind"], fo.issue(fixed)[0]), ("changed", "CruiseNext offer changed: DoubleUp to TripleUp (Nov 7, 2026)"))
    check("Offer fix: the file passes", co.check(fixed, any_schema=False), [])
    fixed["last_change"]["reported"] = True
    check("Offer fix: the next run (schema 2) opens nothing", fo.issue(fo.build(real3, fixed, nov(8))), None)
    check("Offer fix: still no offer is no change", fo.issue(fo.build(offers_page(None), wrong, nov(7))), None)
    check("Offer fix: the same DoubleUp back is an ordinary appeared",
          fo.build(real, wrong, nov(7))["last_change"]["kind"], "appeared")
    for name, data in [("another date", dict(wrong, last_change=dict(wrong["last_change"], on="2026-11-05"))),
                       ("another old text", dict(wrong, last_change=dict(wrong["last_change"], old_text=new_text))),
                       ("a schema 2 file", dict(fo.build(offers_page(None), same, nov(6)), checked_on="2026-11-06"))]:
        check(f"Offer fix: not used with {name}", fo.build(real3, data, nov(7))["last_change"]["kind"], "appeared")

    # The format check refuses anything outside its lists.
    bad_cases = {
        "an extra key": dict(same, guest_email="x"),
        "read_ok true with nothing read": dict(same, multi_credit=None),
        "a banner with a new line": dict(same, multi_credit=dict(same["multi_credit"], text="two\nlines")),
        "unknown cabin type": dict(same, multi_credit=dict(same["multi_credit"], types=["YACHT"])),
        "no banner but text": dict(ended, multi_credit=dict(ended["multi_credit"], text="x")),
        "no banner but credits": dict(ended, multi_credit=dict(ended["multi_credit"], credits=2)),
        "bad marker": dict(same, last_change=dict(same["last_change"], marker="x")),
        "read_ok false without a warning": dict(same, read_ok=False, warnings=[]),
        "types null without a warning": dict(same, multi_credit=dict(same["multi_credit"], types=None)),
        "credits null without a warning": dict(same, multi_credit=dict(same["multi_credit"], credits=None)),
        "5 credits": dict(same, multi_credit=dict(same["multi_credit"], credits=5)),
        "a name that isn't an offer name": dict(same, multi_credit=dict(same["multi_credit"], name="Free stuff")),
        "a name not in the title": dict(same, multi_credit=dict(same["multi_credit"], name="TripleUp!")),
        "the old doubleup key in schema 2": dict({k: v for k, v in same.items() if k != "multi_credit"}, doubleup=same["multi_credit"]),
        "changed with nothing different": dict(trip, last_change=dict(trip["last_change"], old_name="TripleUp!", old_credits=3, old_text=three_text)),
        "schema 3": dict(same, schema_version=3),
    }
    for name, data in bad_cases.items():
        check(f"Offer format check refuses {name}", bool(co.check(data)), True)

    # main(): exactly 1 NCL page load at the CruiseNext address, the issue files, --mark-reported.
    folder = tempfile.mkdtemp(prefix="june-offers-")
    calls = []
    old_request = fo.fp.request

    def fake_request(url, body=None, raw=False, page=False):
        calls.append((url, page))
        return real3
    fo.fp.request = fake_request
    try:
        out, issue_dir = os.path.join(folder, "offers.new.json"), os.path.join(folder, "issue")
        fo.main(["--out", out, "--issue-dir", issue_dir])
        check("Offer main: 1 NCL page load at the CruiseNext address", calls, [(fo.CRUISENEXT_URL, True)])
        check("Offer main: issue files written", sorted(os.listdir(issue_dir)), ["body.md", "marker.txt", "title.txt"])
        fo.main(["--mark-reported", out])
        with open(out, encoding="utf-8") as f:
            saved_file = json.load(f)
        check("Offer main: --mark-reported marks the change", saved_file["last_change"]["reported"], True)
        check("Offer main: the written file passes", co.check(saved_file, any_schema=False), [])
        issue_dir2 = os.path.join(folder, "issue2")
        fo.main(["--previous", out, "--out", os.path.join(folder, "next.json"), "--issue-dir", issue_dir2])
        check("Offer main: next run with the same banner writes no issue", os.path.exists(issue_dir2), False)
    finally:
        fo.fp.request = old_request
    check("Offer: the CruiseNext address passes the address guard", bool(fo.fp.FORBIDDEN.search(fo.CRUISENEXT_URL)), False)


# ---------- Payment data (5.2.0, prices schema 4) ----------

class PaymentNCL:
    """A stand-in for every NCL call fetch_prices.py makes, with NCL's payment options as the
    2026-10-28 research saw them: $50 per guest up to Club Balcony Suite (due in 76 hours), 10%
    of the cruise fare for Suite and Haven (23 hours), final payment 120 days before sailing, and
    the 2-For-1 Deposits offer in the availability answers. The Aura at 5 guests has only Haven
    cabins, so its cheapest cabin is a Haven (as on NCL today). Taxes $100 per guest.

    1 guest (5.4.0), as NCL answered in the probe of 2026-11-15: solo cabins (T1, IT, BT) are
    available only at 1 guest, priced for one; a regular cabin for 1 guest costs twice its per guest
    fare plus taxes for one, with the fare line titled "Free 2nd Guest"; $50 deposit in 84 hours.
    Options change that for a test: no_solo (ships without a solo cabin), one_tax and one_bar
    (other tax or Open Bar lines at 1 guest), one_haven (ships where only The Haven and the solo
    cabins are open for 1 guest), odd_fare (codes whose 1 guest fare isn't twice the 2 guest one)."""
    CATS = {"STUDIO": [("T1", 450)], "INSIDE": [("IX", 380), ("IA", 420), ("IT", 400)], "BALCONY": [("B4", 600), ("BT", 520)],
            "MINISUITE": [("MB", 678)], "SUITE": [("SC", 2000)], "HAVEN": [("H6", 3500)]}
    SOLO = {"T1", "IT", "BT"}
    TAX = 100

    def __init__(self, fail=(), deposit=None, final=None, offer=True, no_solo=(), one_tax=None, one_bar=None,
                 one_haven=(), odd_fare=()):
        self.fail = set(fail)               # (ship_short, guests) whose availability call fails
        self.deposit = deposit or {}        # (ship_short, guests) or (ship_short, 1, code): deposit NCL lists instead of its rule
        self.final = final or {}            # (ship_short, guests): final payment date instead of the rule
        self.offer = offer
        self.no_solo, self.one_haven, self.odd_fare = set(no_solo), set(one_haven), set(odd_fare)
        self.one_tax, self.one_bar = one_tax or {}, one_bar or {}
        self.calls = []
        self.ship = {}

    def cfg_for(self, package_id):
        return next(c for c in fp.SAILINGS if c["ship_short"] == self.ship[str(package_id)])

    def cats(self, ship, guests):
        only_haven = (ship == "Aura" and guests == 5) or (guests == 1 and ship in self.one_haven)
        return {t: [(c, p) for c, p in cats if (c in self.SOLO) == (guests == 1) or c not in self.SOLO]
                for t, cats in self.CATS.items() if not only_haven or t == "HAVEN" or (guests == 1 and t in ("STUDIO", "INSIDE", "BALCONY"))}

    def open(self, ship, guests, code):
        if code in self.SOLO:
            return guests == 1 and ship not in self.no_solo
        if guests == 1 and ship in self.one_haven:
            return code == "H6"
        return True

    def price(self, guests, code, base):
        """NCL's average per guest price (with taxes) for the party."""
        if guests != 1 or code in self.SOLO:
            return base
        return 2 * (base - self.TAX) + self.TAX + (30 if code in self.odd_fare else 0)

    def __call__(self, url, body=None, raw=False, page=False):
        self.calls.append(url)
        for cfg in fp.SAILINGS:
            if url == fp.CRUISE_PAGE_URL.format(code=cfg["start_pages"][0]):
                pid = "2422" if cfg["ship_short"] == "Getaway" else "2572"
                self.ship[pid] = cfg["ship_short"]
                return cruise_page([{"itineraryCode": cfg["start_pages"][0], "packageId": int(pid),
                                     "departureDate": ms(cfg["depart"] + "T04:00:00Z")}])
        if "/itinerary/" in url:
            cfg = self.cfg_for(url.split("packageId=")[1])
            return itinerary(url.split("packageId=")[1], cfg["depart"] + "T00:00:00", ship=cfg["ship_code"], nights=cfg["nights"])
        if "/route-events/" in url:
            cfg = self.cfg_for(url.rsplit("/", 1)[1])
            day = dt.date.fromisoformat(cfg["depart"])
            return [{"date": ms(f"{day + dt.timedelta(days=i)}T00:00:00Z"), "eventType": "port", "title": "Miami",
                     "arrivalTime": "7:00 AM", "departureTime": "4:00 PM"} for i in range(cfg["nights"] + 1)]
        if url == fp.AVAILABILITY_URL:
            f = body["sailingFilters"][0]
            ship, g = self.ship[f["packageId"]], f["numberOfGuests"]
            if (ship, g) in self.fail:
                raise RuntimeError("NCL answered HTTP 500")

            def pricing(code, price):
                if not self.open(ship, g, code):
                    return {"isAvailable": False, "isSoldOut": False, "standardOption": {"pricedCategoryCode": code, "guestCapacity": 0}}
                return {"isAvailable": True, "standardOption": {"pricedCategoryCode": code, "price": self.price(g, code, price),
                                                                "guestCapacity": 1 if code in self.SOLO else 5}}
            types = [{"code": t, "title": t.title(), "stateroomsPricing": [
                {"stateroom": {"title": f"Solo {t.title()}" if code in self.SOLO else f"{t.title()} {code}"}, "categoryPricing": [pricing(code, price)]}
                for code, price in cats]} for t, cats in self.cats(ship, g).items()]
            groups = [{"code": "FREE-AT-SEA", "promotionsInGroup": [
                {"isDefaultInGroup": True, "promotion": {"promotionCodes": ["ALL4CHO"], "stateroomTypes": ["STUDIO", "INSIDE", "BALCONY", "MINISUITE"]}},
                {"isDefaultInGroup": True, "promotion": {"promotionCodes": ["CHOALL4M"], "stateroomTypes": ["SUITE", "HAVEN"]}}]}]
            if self.offer:
                groups.append({"code": "MORE-OFFERS", "promotionsInGroup": [{"promotion": {"promotionCodes": [], "stateroomTypes": [], "offers": [
                    {"code": "2-For-1-Deposits-Offer", "groupingCode": "2-For-1-Deposits-Offer", "title": "2-For-1 Deposits",
                     "description": "Lock-in this vacation today with half off deposits for every two guests on your reservation."}]}}]})
            return {"results": [{"result": {"stateroomTypesPricing": types, "offerGroups": groups}}]}
        if url == fp.PRICE_SUMMARY_URL:
            f = body["stateroomFilters"][0]
            ship, g, code, tcode = self.ship[body["packageId"]], f["numberOfGuests"], f["pricedCategoryCode"], f["stateroomTypeCode"]
            cfg = self.cfg_for(body["packageId"])
            price = self.price(g, code, next(p for c, p in self.CATS[tcode] if c == code))
            tax = self.one_tax.get(ship, self.TAX) if g == 1 else self.TAX
            if f["guests"]:   # the age test: 1 adult, a 15 year old, a 7 year old
                bar, dining = [96, 37.5, 0], [20, 20, 0]
            else:
                bar, dining = [self.one_bar.get(ship, 96) if g == 1 else 96] * g, [20] * g
            fare_total = (price - self.TAX) * g
            deposit = round(fare_total * 0.1, 2) if tcode in ("SUITE", "HAVEN") else 50 * g
            deposit = self.deposit.get((ship, g, code), self.deposit.get((ship, g), deposit))
            final = self.final.get((ship, g), (dt.date.fromisoformat(cfg["depart"]) - dt.timedelta(days=120)).isoformat())
            options = [{"paymentType": "FULL", "amount": 1, "dueDate": final + "T23:59:59"}, {"paymentType": "MONTHLY", "amount": 1},
                       {"isDeposit": True, "paymentType": "HOLD", "amount": deposit, "dueHours": 76}]
            if deposit is not None:
                options.insert(0, {"paymentType": "DEPOSIT", "amount": deposit,
                                   "dueHours": 23 if tcode in ("SUITE", "HAVEN") else 84 if g == 1 else 76, "dueDate": "2026-10-31T23:59:59"})
            guests = lambda xs: [{"price": x} for x in xs]
            fare_line = "Free 2nd Guest" if g == 1 else "Fare"
            return {"staterooms": [{"paymentOptions": options, "pricing": {"priceGroups": [
                {"code": "STATEROOM", "priceItems": [{"code": "x-strikethrough", "itemType": "strikethrough", "title": "Inside"},
                                                     {"code": "fare", "title": fare_line, "guests": guests([price - self.TAX] * g)}]},
                {"code": "FREE-AT-SEA", "priceItems": [
                    {"code": "unlimited-open-bar-offer", "title": "Unlimited Open Bar", "guests": guests(bar)},
                    {"code": "specialty-dining-offer-2-4-nights", "title": "Specialty Dining - 1 Meal", "guests": guests(dining)}]},
                {"code": "TAXES-AND-FEES", "priceItems": [{"code": "taxes-and-fees", "title": "Taxes", "guests": guests([tax] * g)}]}]}}],
                "total": {"grandTotal": round(price * g) + sum(bar) + sum(dining)}}
        raise AssertionError(f"unexpected NCL call {url}")


RATES_PAGE = ("Prices are Per Person Per Day 1-8 (Adult) $49.99 1-2 (Child) $40 "
              "2 - 5 Nights $32 USD 6+ Nights $28.50 USD Unlimited Soda Beverage Package is $12.50 USD per person per day "
              "$25.00 USD per person per day for The Haven and Suites; $20.00 USD per person per day for Club Balcony Suite and below "
              "All guests 3 years or older")


def test_eastern_dates():
    """Every date-only field fetch_prices.py writes is the Eastern date (5.2.0): the evening run of
    Oct 28 at 10:14 PM Eastern is Oct 29 by UTC date."""
    utc = lambda s: dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    check("Eastern date: 10:14 PM Eastern on Oct 28 (Oct 29 by UTC date)", fp.eastern_day(utc("2026-10-29T02:14:00Z")), "2026-10-28")
    check("Eastern date: 10 PM Eastern on Nov 1 (after daylight saving time ends)", fp.eastern_day(utc("2026-11-02T03:00:00Z")), "2026-11-01")
    check("Eastern date: morning run", fp.eastern_day(utc("2026-10-29T10:20:00Z")), "2026-10-29")
    cfg = {"id": "getaway-2027-06-11", "ship_short": "Getaway"}
    keep_log = fp.log
    fp.log = lambda m: None
    try:
        status = {str(g): {"updated": True, "as_of": "2026-10-29T02:14:00Z"} for g in fp.GUEST_COUNTS}
        summaries = {g: {"type": "BALCONY", "category": "BF", "deposit": 50.0 * g, "deposit_due_hours": 73,
                         "final_payment_due": "2027-02-11", "fare_total": 1000} for g in fp.GUEST_COUNTS}
        pay = fp.payment_info(cfg, summaries, status, None, {}, utc("2026-10-29T02:14:00Z"), {"deposits": []}, [])
        check("deposit checked date: the Eastern date of an evening run", (pay["standard_deposit_per_guest"], pay["standard_deposit_checked_at"]), (50.0, "2026-10-28"))
        # No standard deposit today: the previous one is kept for 3 Eastern days.
        kept = {str(g): {"updated": False, "as_of": "2026-10-25T10:20:00Z"} for g in fp.GUEST_COUNTS}
        prev_s = {"payment": {"standard_deposit_per_guest": 50, "standard_deposit_checked_at": "2026-10-25", "final_payment_due": "2027-02-11"}}
        pay = fp.payment_info(cfg, {}, kept, prev_s, {}, utc("2026-10-29T02:14:00Z"), {"deposits": []}, [])
        check("deposit kept 3 Eastern days (4 by UTC date)", pay["standard_deposit_checked_at"], "2026-10-25")
        pay = fp.payment_info(cfg, {}, kept, prev_s, {}, utc("2026-10-29T10:20:00Z"), {"deposits": []}, [])
        check("deposit not kept after 4 Eastern days", pay["standard_deposit_per_guest"], None)
        grat = {"open_bar": {"title": "Unlimited Open Bar", "per_guest": 96, "soda_under_21_position_2": 37.5, "checked_at": "2026-10-13"},
                "specialty_dining": {"title": "Specialty Dining - 1 Meal", "per_guest": 20, "checked_at": "2026-10-13"}}
        previous = {"saved_at": "2026-10-13T10:00:00Z", "sailings": [{"id": cfg["id"], "gratuities": grat}],
                    "checks": {"ages": [{"sailing": cfg["id"], "ok": True, "expected": 1, "ncl_total": 1}]}}
        g, _ = fp.kept_gratuities(cfg, previous["sailings"][0], previous, utc("2026-10-17T02:00:00Z"), RuntimeError("x"), [])
        check("gratuities kept 3 Eastern days (Oct 16, 10 PM Eastern; 4 by UTC date)", g is grat, True)
        rules = fp.deposit_rules({"deposits": [{"rule": fp.PERCENT_RULE, "ok": True, "sailing": "aura-2027-06-14", "category": "H6", "guests": 5}]},
                                 None, fp.eastern_day(utc("2026-10-29T02:14:00Z")), [])
        check("Suite and Haven rule confirmed on the Eastern date", rules["confirmed_on"], "2026-10-28")
    finally:
        fp.log = keep_log


def price_run(ncl, folder, previous=None, name="prices.json"):
    """One whole fetch_prices.py run (main) against the stand-in for NCL, no network. Returns the
    data file it wrote and what it printed for the GitHub run page."""
    import contextlib
    import io
    out = os.path.join(folder, name)
    prev = os.path.join(folder, "previous.json")
    if previous is not None:
        with open(prev, "w", encoding="utf-8") as f:
            json.dump(previous, f)
    elif os.path.exists(prev):
        os.remove(prev)
    keep = (fp.request, fp.page_text, fp.deck_finder_decks, fp.log, fp.PAUSE_SECONDS, sys.argv)
    fp.request, fp.page_text, fp.deck_finder_decks, fp.log, fp.PAUSE_SECONDS = ncl, (lambda url: RATES_PAGE), (lambda ship: {}), (lambda m: None), 0
    sys.argv = ["fetch_prices.py", "--out", out, "--previous", prev]
    printed = io.StringIO()
    try:
        with contextlib.redirect_stdout(printed):
            fp.main()
    finally:
        fp.request, fp.page_text, fp.deck_finder_decks, fp.log, fp.PAUSE_SECONDS, sys.argv = keep
    with open(out, encoding="utf-8") as f:
        return json.load(f), printed.getvalue()


def test_payment():
    import check_prices
    folder = tempfile.mkdtemp(prefix="june-payment-")

    # NCL's own answer, saved 2026-10-06 (Getaway B4, 4 guests): DEPOSIT $200 in 74 hours, FULL by
    # Feb 11, 2027, and the HOLD payment option, which is never used.
    check("saved NCL price summary: deposit, hours, final payment date", fp.payment_options(saved("price_summary_getaway_B4_4_2026-10-06")),
          (200.0, 74, "2027-02-11"))
    check("no DEPOSIT option: only the HOLD option's amount is never used", fp.payment_options(
        {"staterooms": [{"paymentOptions": [{"isDeposit": True, "paymentType": "HOLD", "amount": 100, "dueHours": 76}]}]}), (None, None, None))
    check("unreadable payment options: nothing guessed", fp.payment_options(
        {"staterooms": [{"paymentOptions": [{"paymentType": "DEPOSIT", "amount": "100"}, {"paymentType": "FULL", "dueDate": "soon"}]}]}), (None, None, None))
    check("no payment options at all", fp.payment_options({"staterooms": [{}]}), (None, None, None))

    # NCL's deposit offer, read like Kids Sail Free, or from the group's own offer list.
    in_promo = {"offerGroups": [{"code": "MORE-OFFERS", "promotionsInGroup": [{"promotion": {"promotionCodes": ["X1"], "stateroomTypes": ["INSIDE"],
                "offers": [{"code": "2-For-1-Deposits-Offer", "title": "2-For-1 Deposits", "description": "half off deposits"}]}}]}]}
    check("deposit offer read from offerGroups", fp.deposit_offer(in_promo),
          {"title": "2-For-1 Deposits", "short": None, "description": "half off deposits", "codes": ["X1"], "types": ["INSIDE"]})
    in_group = {"offerGroups": [{"code": "MORE-OFFERS", "offers": [{"groupingCode": "Reduced-Deposit-Offer", "title": "Reduced Deposits"}]}]}
    check("deposit offer read from a group's own offers", fp.deposit_offer(in_group)["title"], "Reduced Deposits")
    check("no deposit offer listed: None", fp.deposit_offer(KSF_ANSWER), None)

    # A whole run: 32 NCL calls (5.4.0: 26 before, plus 1 availability call and 2 price summaries
    # per ship for 1 guest), nothing more.
    ncl = PaymentNCL()
    data, printed = price_run(ncl, folder)
    check("payment run: 30 calls through request() (2 cruise pages, 2 itinerary, 2 route-events, 10 availability, 14 price summaries), "
          "plus the 2 terms pages = 32 NCL calls", len(ncl.calls), 30)
    check("payment run: schema 5 file passes the format check", check_prices.check(data), [])
    g, a = data["sailings"]
    check("Getaway: $50 per guest, final payment Feb 11, 2027", (g["payment"]["standard_deposit_per_guest"], g["payment"]["final_payment_due"]), (50.0, "2027-02-11"))
    check("Aura: final payment Feb 14, 2027", a["payment"]["final_payment_due"], "2027-02-14")
    check("Getaway deposits at 2 to 5 guests from NCL's summaries", [g["payment"]["by_guests"][k]["deposit"] for k in "2345"], [100.0, 150.0, 200.0, 250.0])
    check("Aura at 5 guests: the Haven's deposit, 10% of its fare", (a["payment"]["by_guests"]["5"]["deposit"], a["payment"]["by_guests"]["5"]["deposit_type"],
                                                                   a["payment"]["by_guests"]["5"]["due_hours"]), (1700.0, "HAVEN", 23))
    check("Suite and Haven rule confirmed today on the Aura Haven", (data["deposit_rules"]["percent_of_fare"], data["deposit_rules"]["confirmed_by"]),
          (10, "aura-2027-06-14 H6 at 5 guests"))
    check("deposit checks: 7 per guest and 1 percent, plus 2 for 1 guest per ship, all ok",
          (len(data["checks"]["deposits"]), all(c["ok"] for c in data["checks"]["deposits"])), (12, True))
    check("deposit offer from the availability answers", g["payment"]["deposit_offer"]["title"], "2-For-1 Deposits")
    check("no warnings on a clean run", data["warnings"], [])
    check("run page notice for deposits", "::notice title=Deposits Getaway::$50 per guest up to Club Balcony Suite, Suite and Haven 10% of the fare, final payment 2027-02-11, offer: 2-For-1 Deposits" in printed, True)

    # Next day: the Getaway's 4 guest availability fails; its kept summary carries yesterday's deposit.
    day2, _ = price_run(PaymentNCL(fail={("Getaway", 4)}), folder, previous=data)
    g2 = day2["sailings"][0]
    check("failed party size: kept deposit with the kept prices' time", (g2["payment"]["by_guests"]["4"]["deposit"], g2["payment"]["by_guests"]["4"]["as_of"]),
          (200.0, g["party_sizes"]["4"]["as_of"]))
    check("failed party size: file passes the format check", check_prices.check(day2), [])

    # The kept prices come from a file written before deposits were read (schema 3).
    old = json.loads(json.dumps(data))
    old["schema_version"] = 3
    for k in ("deposit_rules",):
        old.pop(k)
    old["checks"].pop("deposits")
    for s in old["sailings"]:
        s.pop("payment")
        for ps in s["price_summaries"]:
            for k in ("deposit", "deposit_due_hours", "final_payment_due"):
                ps.pop(k)
    first, _ = price_run(PaymentNCL(fail={("Getaway", 4)}), folder, previous=old)
    e = first["sailings"][0]["payment"]["by_guests"]["4"]
    check("kept schema 3 prices: deposit empty with why", (e["deposit"], e["why"]), (None, "the kept prices are from before deposits were read"))
    check("kept schema 3 prices: warning names the ship", "Getaway: no deposit for 4 guests (the kept prices are from before deposits were read); left empty" in first["warnings"], True)
    check("kept schema 3 prices: file passes the format check", check_prices.check(first), [])

    # NCL's Haven deposit is no longer 10%: the rule is left empty with a warning.
    bad, _ = price_run(PaymentNCL(deposit={("Aura", 5): 500}), folder, previous=data)
    check("Haven deposit not 10%: rule left empty", bad["deposit_rules"]["percent_of_fare"], None)
    check("Haven deposit not 10%: warning", any(w.startswith("Deposits: NCL's Suite and Haven deposit is not 10%") for w in bad["warnings"]), True)
    check("Haven deposit not 10%: file still passes the format check", check_prices.check(bad), [])
    # The next run has no Suite or Haven summary: the empty rule stays empty, with a warning again.
    later, _ = price_run(PaymentNCL(fail={("Aura", 5)}), folder, previous=bad)
    check("no Suite or Haven summary after a failed check: still empty, warned",
          (later["deposit_rules"]["percent_of_fare"], any(w.startswith("Deposits: no Suite or Haven") for w in later["warnings"])), (None, True))
    check("no Suite or Haven summary after a failed check: file passes", check_prices.check(later), [])
    # No Suite or Haven summary and a good previous rule: kept as it was confirmed.
    kept, _ = price_run(PaymentNCL(fail={("Aura", 5)}), folder, previous=data)
    check("no Suite or Haven summary: previous rule kept with its date", (kept["deposit_rules"]["percent_of_fare"], kept["deposit_rules"]["confirmed_on"]),
          (10, data["deposit_rules"]["confirmed_on"]))
    # The first schema 4 run without a Suite or Haven summary: the research of 2026-10-28.
    research, _ = price_run(PaymentNCL(fail={("Aura", 5)}), folder, previous=old)
    check("first run, no Suite or Haven summary: the research rule", (research["deposit_rules"]["percent_of_fare"], research["deposit_rules"]["confirmed_on"]), (10, "2026-10-28"))

    # Standard deposits that differ by party size: left empty with a warning.
    odd, _ = price_run(PaymentNCL(deposit={("Getaway", 3): 300}), folder, previous=data)
    check("deposit per guest differs: standard deposit empty", odd["sailings"][0]["payment"]["standard_deposit_per_guest"], None)
    check("deposit per guest differs: the odd party size fails its check",
          [c["guests"] for c in odd["checks"]["deposits"] if not c["ok"]], [3])
    check("deposit per guest differs: file passes the format check", check_prices.check(odd), [])
    # NCL lists no deposit: empty with a warning, never the HOLD option's amount.
    none, _ = price_run(PaymentNCL(deposit={("Getaway", 2): None}), folder, previous=data)
    e = none["sailings"][0]["payment"]["by_guests"]["2"]
    check("no DEPOSIT option: deposit empty with why", (e["deposit"], e["why"], e["due_hours"]), (None, "NCL's price summary listed no deposit", None))
    check("no DEPOSIT option: file passes", check_prices.check(none), [])
    # Final payment dates that disagree: the earliest, with a warning.
    diff, _ = price_run(PaymentNCL(final={("Getaway", 5): "2027-02-01"}), folder, previous=data)
    check("final payment dates differ: the earliest", diff["sailings"][0]["payment"]["final_payment_due"], "2027-02-01")
    check("final payment dates differ: warning", any(w.startswith("Getaway: NCL's final payment dates differ") for w in diff["warnings"]), True)
    # No deposit offer listed today.
    plain, _ = price_run(PaymentNCL(offer=False), folder, previous=data)
    check("no deposit offer listed: null", plain["sailings"][0]["payment"]["deposit_offer"], None)
    check("no deposit offer listed: file passes", check_prices.check(plain), [])

    # The format check on schema 4 files.
    def broken(change):
        d = json.loads(json.dumps(data))
        change(d)
        return check_prices.check(d)
    check("format: a file without payment fails", any("payment must have" in x for x in broken(lambda d: d["sailings"][0].pop("payment"))), True)
    check("format: a file without deposit_rules fails", any("deposit_rules is missing" in x for x in broken(lambda d: d.pop("deposit_rules"))), True)
    check("format: an empty deposit without a warning fails",
          any("empty deposit needs" in x for x in broken(lambda d: d["sailings"][0]["payment"]["by_guests"]["2"].update(deposit=None, why="x", due_hours=None))), True)
    check("format: an empty final payment date without a warning fails",
          any("final_payment_due is empty" in x for x in broken(lambda d: d["sailings"][1]["payment"].update(final_payment_due=None))), True)
    check("format: a final payment date after sailing fails",
          any("before the sail date" in x for x in broken(lambda d: d["sailings"][1]["payment"].update(final_payment_due="2027-07-01"))), True)
    check("format: an empty Suite and Haven rule without a warning fails",
          any("percent_of_fare is empty" in x for x in broken(lambda d: d["deposit_rules"].update(percent_of_fare=None, confirmed_on=None))), True)
    check("format: a failed Suite and Haven check with the rule still set fails",
          any("check failed but deposit_rules" in x for x in broken(lambda d: next(c for c in d["checks"]["deposits"] if c["rule"] == fp.PERCENT_RULE).update(ok=False))), True)
    check("format: a failed per guest check with the deposit still set fails",
          any("check failed but payment.standard" in x for x in broken(lambda d: d["checks"]["deposits"][0].update(ok=False))), True)
    check("format: a deposit offer without a title fails",
          any("deposit_offer must be" in x for x in broken(lambda d: d["sailings"][0]["payment"]["deposit_offer"].update(title=""))), True)
    check("format: a schema 3 file is refused, in the release check too", ("schema_version must be 5" in check_prices.check(old),
          "schema_version must be 5" in check_prices.check(old, allow_schema_4=True)), (True, True))


def test_one_guest():
    """Party size 1, solo travelers (5.4.0): two price summaries at 1 guest (regular and solo), the
    1 guest deposits checked on their own, the single supplement facts, and party size 1 never
    failing the run or stopping the prices for 2 to 5 guests."""
    import check_prices
    folder = tempfile.mkdtemp(prefix="june-one-guest-")
    ncl = PaymentNCL()
    data, printed = price_run(ncl, folder)
    g, a = data["sailings"]
    check("1 guest: schema 5 with party sizes 1 to 5", (data["schema_version"], data["guest_counts"], sorted(g["party_sizes"])),
          (5, [1, 2, 3, 4, 5], ["1", "2", "3", "4", "5"]))
    check("1 guest: 2 availability calls and 4 price summaries more than 2 to 5 guests",
          (sum(u == fp.AVAILABILITY_URL for u in ncl.calls), sum(u == fp.PRICE_SUMMARY_URL for u in ncl.calls)), (10, 14))
    ones = [(x["kind"], x["category"], x["grand_total"]) for x in g["price_summaries"] if x["guests"] == 1]
    check("1 guest: the cheapest regular cabin (IX: $660 cabin, $776 with Free at Sea) and the cheapest solo cabin (IT)",
          ones, [("regular", "IX", 776), ("solo", "IT", 516)])
    check("1 guest: every price summary has its kind", sorted({x["kind"] for x in g["price_summaries"]}), ["regular", "solo"])
    check("1 guest: a formula check for each kind", sorted(c["kind"] for c in data["checks"]["formula"] if c["sailing"] == g["id"] and c["guests"] == 1),
          ["regular", "solo"])
    cat = lambda s, code: next(c for t in s["types"] for c in t["categories"] if c["code"] == code)
    check("1 guest: solo cabins priced for one", (cat(g, "IT")["by_guests"]["1"]["cabin_total"], cat(g, "T1")["by_guests"]["1"]["cabin_total"]), (400, 450))
    check("1 guest: solo cabins not available for 2 guests, capacity still from the 2 guest call",
          (cat(g, "IT")["by_guests"]["2"]["available"], cat(g, "IT")["by_guests"]["2"]["reason"], cat(g, "IT")["capacity"]),
          (False, "Not available for 2 guests", None))
    check("1 guest: a regular cabin at twice the per guest fare plus taxes for one", cat(g, "IA")["by_guests"]["1"]["cabin_total"], 740)
    check("1 guest: no added_vs_2 at 1 guest", "added_vs_2" in cat(g, "IA")["by_guests"]["1"], False)
    check("1 guest: by_guests keys in order 1 to 5", list(cat(g, "IA")["by_guests"]), ["1", "2", "3", "4", "5"])
    check("1 guest: single supplement, every regular category twice the 2 guest fare, NCL's fare line",
          {k: g["single_supplement"][k] for k in ("categories", "matching", "all_match", "ncl_fare_line")},
          {"categories": 6, "matching": 6, "all_match": True, "ncl_fare_line": "Free 2nd Guest"})
    pay = g["payment"]
    check("1 guest: the regular and solo deposits, $50 in 84 hours, confirmed against $50 per guest",
          (pay["by_guests"]["1"]["deposit"], pay["by_guests"]["1"]["deposit_category"], pay["solo_1_guest"]["deposit"],
           pay["solo_1_guest"]["deposit_category"], pay["solo_1_guest"]["due_hours"], pay["standard_deposit_1_guest_ok"]),
          (50.0, "IX", 50.0, "IT", 84, True))
    check("1 guest: NCL's deposit offer as listed in the 1 guest answer", pay["deposit_offer_1_guest"]["title"], "2-For-1 Deposits")
    check("1 guest: no Suite or Haven summary for 1 guest, so David confirms those", data["deposit_rules"]["one_guest_confirmed_on"], None)
    check("1 guest: no warnings on a clean run", data["warnings"], [])
    check("1 guest: run page notice", "::notice title=1 guest Getaway::updated today, cheapest solo IT $516 with Free at Sea, "
          "single supplement: 6 of 6 regular categories charge twice the 2 guest fare per guest" in printed, True)

    # The price summaries by party size: a failed 2 guest call keeps the 2 guest entry, never a 1 guest one.
    day2, _ = price_run(PaymentNCL(fail={("Getaway", 2)}), folder, previous=data)
    g2 = day2["sailings"][0]
    two = [x for x in g2["price_summaries"] if x["guests"] == 2]
    check("kept 2 guest prices: the 2 guest summary (not a 1 guest one) is kept", [(x["kind"], x["category"], x["guests"]) for x in two], [("regular", "IX", 2)])
    check("kept 2 guest prices: its deposit is the 2 guest deposit", g2["payment"]["by_guests"]["2"]["deposit"], 100.0)
    check("kept 2 guest prices: 1 guest summaries are today's own", [(x["kind"], x["guests"]) for x in g2["price_summaries"] if x["guests"] == 1],
          [("regular", 1), ("solo", 1)])
    check("kept 2 guest prices: file passes", check_prices.check(day2), [])
    # A failed 1 guest call with yesterday's 1 guest prices: both kept, each where it belongs.
    day3, _ = price_run(PaymentNCL(fail={("Getaway", 1)}), folder, previous=data)
    g3 = day3["sailings"][0]
    check("1 guest failed: kept prices, not updated, with their time", (g3["party_sizes"]["1"]["updated"], g3["party_sizes"]["1"]["checked"],
          g3["party_sizes"]["1"]["as_of"]), (False, True, g["party_sizes"]["1"]["as_of"]))
    check("1 guest failed: both kept 1 guest summaries, by kind", [(x["kind"], x["category"]) for x in g3["price_summaries"] if x["guests"] == 1],
          [("regular", "IX"), ("solo", "IT")])
    check("1 guest failed: the kept deposits (regular and solo)", (g3["payment"]["by_guests"]["1"]["deposit_category"], g3["payment"]["solo_1_guest"]["deposit_category"]),
          ("IX", "IT"))
    check("1 guest failed: the kept prices", cat(g3, "IT")["by_guests"]["1"]["cabin_total"], 400)
    check("1 guest failed: the 2 to 5 guest prices are today's", all(g3["party_sizes"][k]["updated"] for k in "2345"), True)
    check("1 guest failed: kept formula checks for 1 guest", sorted(c["kind"] for c in day3["checks"]["formula"] if c["sailing"] == g3["id"] and c["guests"] == 1),
          ["regular", "solo"])
    check("1 guest failed: file passes", check_prices.check(day3), [])

    # A failed 1 guest call and nothing to keep: not checked today, the run goes on.
    for name, prev in (("no previous file", None), ("a schema 4 previous file", schema4(json.loads(json.dumps(data)))),
                       ("kept prices more than 3 days old", None)):
        if name == "a schema 4 previous file":
            prev["schema_version"] = 4
            for s in prev["sailings"]:
                s["party_sizes"].pop("1")
        if name.startswith("kept"):
            prev = json.loads(json.dumps(data))
            prev["sailings"][0]["party_sizes"]["1"]["as_of"] = "2020-01-01T10:00:00Z"
        nc, _ = price_run(PaymentNCL(fail={("Getaway", 1)}), folder, previous=prev)
        gn = nc["sailings"][0]
        check(f"1 guest not checked ({name}): party size 1", (gn["party_sizes"]["1"]["updated"], gn["party_sizes"]["1"]["checked"], gn["party_sizes"]["1"]["as_of"]),
              (False, False, None))
        check(f"1 guest not checked ({name}): every cabin 'Not checked today'",
              {c["by_guests"]["1"]["reason"] for t in gn["types"] for c in t["categories"]}, {"Not checked today"})
        check(f"1 guest not checked ({name}): warning", any(w.startswith("Getaway: prices for 1 guest not checked today") for w in nc["warnings"]), True)
        check(f"1 guest not checked ({name}): no 1 guest summary, deposit or supplement",
              ([x for x in gn["price_summaries"] if x["guests"] == 1], gn["payment"]["solo_1_guest"], gn["single_supplement"]), ([], None, None))
        check(f"1 guest not checked ({name}): 2 to 5 guests updated, the Aura untouched",
              (all(gn["party_sizes"][k]["updated"] for k in "2345"), nc["sailings"][1]["party_sizes"]["1"]["updated"]), (True, True))
        check(f"1 guest not checked ({name}): file passes", check_prices.check(nc), [])
    # 2 to 5 guests all failing still fails the run, even when 1 guest worked.
    try:
        price_run(PaymentNCL(fail={("Aura", n) for n in (2, 3, 4, 5)}), folder, previous=None)
        check("every party size from 2 to 5 failed: the run fails", False, True)
    except RuntimeError as e:
        check("every party size from 2 to 5 failed: the run fails", "Every party size from 2 to 5 guests failed" in str(e), True)
    # Every party size failing on a ship, 1 guest included: still that rule, never a 1 guest one.
    try:
        price_run(PaymentNCL(fail={("Aura", n) for n in (1, 2, 3, 4, 5)}), folder, previous=None)
        check("every party size failed: the run fails", False, True)
    except RuntimeError as e:
        check("every party size failed: the run fails", "Every party size from 2 to 5 guests failed" in str(e), True)

    # A 1 guest summary whose tax or Open Bar line differs from the amounts the page uses fails party size 1 only.
    for name, opts in (("tax line", {"one_tax": {"Getaway": 120}}), ("Open Bar line", {"one_bar": {"Getaway": 192}})):
        bad, _ = price_run(PaymentNCL(**opts), folder, previous=None)
        gb = bad["sailings"][0]
        check(f"1 guest {name} differs: party size 1 not checked, 2 to 5 updated",
              (gb["party_sizes"]["1"]["checked"], all(gb["party_sizes"][k]["updated"] for k in "2345")), (False, True))
        check(f"1 guest {name} differs: logged in checks.one_guest", [c["ok"] for c in bad["checks"]["one_guest"] if c["sailing"] == gb["id"]], [False, False])
        check(f"1 guest {name} differs: file passes", check_prices.check(bad), [])
    # No solo cabin available on the Aura: only the regular summary, which is not a failure.
    ns = PaymentNCL(no_solo={"Aura"})
    nos, _ = price_run(ns, folder, previous=None)
    an = nos["sailings"][1]
    check("no solo cabin: 1 price summary fewer", sum(u == fp.PRICE_SUMMARY_URL for u in ns.calls), 13)
    check("no solo cabin: updated, regular summary only, no solo deposit",
          (an["party_sizes"]["1"]["updated"], [x["kind"] for x in an["price_summaries"] if x["guests"] == 1], an["payment"]["solo_1_guest"]), (True, ["regular"], None))
    check("no solo cabin: file passes", check_prices.check(nos), [])
    # NCL's 1 guest deposit isn't the per guest one: left to David at 1 guest, $50 per guest kept for 2 to 5.
    odd, _ = price_run(PaymentNCL(deposit={("Getaway", 1, "IT"): 100}), folder, previous=None)
    po = odd["sailings"][0]["payment"]
    check("1 guest deposit differs: not confirmed, standard deposit for 2 to 5 unchanged",
          (po["standard_deposit_1_guest_ok"], po["standard_deposit_per_guest"], po["solo_1_guest"]["deposit"]), (False, 50.0, 100.0))
    check("1 guest deposit differs: warning", any(w.startswith("Getaway: NCL's deposit for 1 guest today") and "left to David" in w for w in odd["warnings"]), True)
    check("1 guest deposit differs: the per guest check of 2 to 5 guests passes", all(c["ok"] for c in odd["checks"]["deposits"] if c["rule"] == fp.PER_GUEST_RULE), True)
    check("1 guest deposit differs: file passes", check_prices.check(odd), [])
    # Only The Haven open for 1 guest on the Aura: its 10% deposit confirms the rule for 1 guest.
    hv, _ = price_run(PaymentNCL(one_haven={"Aura"}), folder, previous=None)
    check("1 guest Haven: 10% confirmed for 1 guest today", (hv["deposit_rules"]["one_guest_confirmed_on"], hv["deposit_rules"]["percent_of_fare"]),
          (fp.eastern_day(dt.datetime.now(dt.timezone.utc)), 10))
    check("1 guest Haven: file passes", check_prices.check(hv), [])
    hb, _ = price_run(PaymentNCL(one_haven={"Aura"}, deposit={("Aura", 1, "H6"): 999}), folder, previous=hv)
    check("1 guest Haven not 10%: empty for 1 guest, the 2 to 5 guest rule unchanged", (hb["deposit_rules"]["one_guest_confirmed_on"], hb["deposit_rules"]["percent_of_fare"]),
          (None, 10))
    check("1 guest Haven not 10%: warning", any(w.startswith("Deposits: NCL's Suite or Haven deposit for 1 guest") for w in hb["warnings"]), True)
    check("1 guest Haven not 10%: file passes", check_prices.check(hb), [])
    # A regular category whose 1 guest fare isn't twice the 2 guest one: the page leaves the "today" part out.
    sp, _ = price_run(PaymentNCL(odd_fare={"IA"}), folder, previous=None)
    check("single supplement: one category differs", {k: sp["sailings"][0]["single_supplement"][k] for k in ("categories", "matching", "all_match")},
          {"categories": 6, "matching": 5, "all_match": False})

    # The format check on the 1 guest data.
    def broken(change, base=data):
        d = json.loads(json.dumps(base))
        change(d)
        return check_prices.check(d)
    has = lambda errs, text: any(text in e for e in errs)
    check("format: a 1 guest summary without its kind fails", has(broken(lambda d: d["sailings"][0]["price_summaries"][0].pop("kind")), "kind regular or solo"), True)
    check("format: a solo summary at 2 guests fails",
          has(broken(lambda d: next(x for x in d["sailings"][0]["price_summaries"] if x["guests"] == 2).update(kind="solo")), "solo at 1 guest only"), True)
    check("format: a missing 1 guest formula check fails", has(broken(lambda d: d["checks"].update(formula=[c for c in d["checks"]["formula"]
          if not (c["guests"] == 1 and c["kind"] == "solo")])), "checks.formula at 1 guest"), True)
    check("format: by_guests without 1 fails", has(broken(lambda d: d["sailings"][0]["types"][0]["categories"][0]["by_guests"].pop("1")), "exactly the keys 1, 2, 3, 4, 5"), True)
    check("format: party size 1 not checked without a warning fails",
          has(broken(lambda d: d.update(warnings=[]), base=nc), "not checked without a warning"), True)
    check("format: not checked but a cabin priced for 1 guest fails",
          has(broken(lambda d: d["sailings"][0]["types"][1]["categories"][0]["by_guests"].update({"1": {"available": True, "sold_out": False, "price_pp": 1.0, "cabin_total": 1}}), base=nc),
              "must be unavailable"), True)
    check("format: only party size 1 can be not checked",
          has(broken(lambda d: d["sailings"][0]["party_sizes"]["3"].update(checked=False)), "only party size 1"), True)
    check("format: a failed 1 guest deposit check with the deposit still confirmed fails",
          has(broken(lambda d: d["sailings"][0]["payment"].update(standard_deposit_1_guest_ok=True), base=odd), "1 guest deposit check failed"), True)
    check("format: an unconfirmed 1 guest deposit without a warning fails",
          has(broken(lambda d: (d["sailings"][0]["payment"].update(standard_deposit_1_guest_ok=None), d.update(warnings=[]))), "no warning"), True)
    check("format: single_supplement that doesn't add up fails",
          has(broken(lambda d: d["sailings"][0]["single_supplement"].update(matching=3)), "all_match"), True)
    check("format: single_supplement missing fails", has(broken(lambda d: d["sailings"][0].pop("single_supplement")), "single_supplement is missing"), True)
    check("format: a 1 guest check that failed with party size 1 updated fails",
          has(broken(lambda d: d["checks"]["one_guest"][0].update(ok=False)), "1 guest check failed but party size 1 is updated"), True)
    check("format: one_guest_confirmed_on missing fails", has(broken(lambda d: d["deposit_rules"].pop("one_guest_confirmed_on")), "one_guest_confirmed_on is missing"), True)
    # The schema 5 test copies the page tests use (test_tools.schema5 and not_checked_1) pass too.
    with open(os.path.join(os.path.dirname(TOOLS), "data", "prices.json"), encoding="utf-8") as f:
        real = json.load(f)
    check("format: the schema 5 test copy of today's prices passes", check_prices.check(schema5(real)), [])
    check("format: the not checked test copy passes", check_prices.check(not_checked_1(real)), [])


def test_saved_one_guest():
    """NCL's own 1 guest answers from the probe of 2026-11-15 (tools/test_data/, response bodies only;
    the HOLD payment option's due date and every cabin number replaced with "REMOVED"): read the
    way fetch_prices.py reads them."""
    one = lambda name: saved(name + "_1_2026-11-15")
    for name in ("price_summary_getaway_IT", "price_summary_getaway_IF", "price_summary_aura_T1", "price_summary_aura_IF"):
        allowed = []
        check(f"saved {name}: passes the hold guard as a price summary (only the HOLD payment option)",
              (fp.hold_signal(one(name), price_summary=True, allowed=allowed), len(allowed)), (None, 1))
        check(f"saved {name}: would stop the run as any other answer", fp.hold_signal(one(name)) is not None, True)
    for name in ("availability_getaway", "availability_aura", "cabin_availability_aura_I4", "cabin_availability_getaway_IT"):
        check(f"saved {name}: no hold signal", fp.hold_signal(one(name)), None)
    # The availability answers: solo cabins, the default Free at Sea codes, the deposit offer.
    rows = {}
    for ship in ("getaway", "aura"):
        res = one(f"availability_{ship}")["results"][0]["result"]
        rows[ship] = {so["pricedCategoryCode"]: (cp.get("isAvailable"), so.get("price"))
                      for t in res["stateroomTypesPricing"] for sp in t["stateroomsPricing"] for cp in sp["categoryPricing"]
                      for so in [cp.get("standardOption") or {}] if so.get("pricedCategoryCode")}
        check(f"saved {ship} availability: default Free at Sea codes", fp.default_fare_codes(res),
              {"STUDIO": "ALL4CHO", "INSIDE": "ALL4CHO", "OCEANVIEW": "ALL4CHO", "MINISUITE": "ALL4CHO", "BALCONY": "ALL4CHO", "HAVEN": "CHOALL4M", "SUITE": "CHOALL4M"})
        check(f"saved {ship} availability: NCL's deposit offer at 1 guest", fp.deposit_offer(res)["title"], "2-For-1 Deposits")
        check(f"saved {ship} availability: no Kids Sail Free", fp.kids_sail_free(res), None)
    check("saved Getaway: every solo cabin available for 1 guest", [rows["getaway"][c] for c in ("T1", "IT", "OT", "BT")],
          [(True, 539), (True, 509), (True, 569), (True, 639)])
    check("saved Aura: Solo Inside and Solo Oceanview sold out", [rows["aura"][c] for c in ("T1", "IT", "OT", "BT")],
          [(True, 2089), (False, None), (False, None), (True, 3109)])
    # The price summaries, as fetch_price_summary reads them, against the page's amounts.
    keep = fp.request
    try:
        for ship, code, tcode, avail, taxes, bar, dining in (("getaway", "IT", "INSIDE", 509, 150, 96, 20), ("getaway", "IF", "INSIDE", 548, 150, 96, 20),
                                                             ("aura", "T1", "STUDIO", 2089, 160, 160, 40), ("aura", "IF", "INSIDE", 2098, 160, 160, 40)):
            fp.request = lambda url, body=None, raw=False, page=False, n=f"price_summary_{ship}_{code}": one(n)
            cfg = dict(next(c for c in fp.SAILINGS if c["id"].startswith(ship)), package_id="1")
            sm = fp.fetch_price_summary(cfg, 1, tcode, code, "ALL4CHO")
            sm["kind"] = "solo" if code in fp.SOLO_CODES else "regular"
            f = fp.formula_check(cfg, 1, sm, avail, sm["kind"])
            check(f"saved {ship} {code}: formula check (availability price + Open Bar + Specialty Dining = NCL's total)", (f["ok"], f["ncl_total"]),
                  (True, avail + bar + dining))
            grat = {"open_bar": {"per_guest": bar}, "specialty_dining": {"per_guest": dining}}
            check(f"saved {ship} {code}: tax and gratuity lines equal the page's amounts", [c["ok"] for c in fp.one_guest_checks(cfg, [sm], taxes, grat)], [True])
            check(f"saved {ship} {code}: $50 deposit in 84 hours", (sm["deposit"], sm["deposit_due_hours"]), (50.0, 84))
            check(f"saved {ship} {code}: NCL's fare line is 'Free 2nd Guest'", sm["fare_title"], "Free 2nd Guest")
    finally:
        fp.request = keep


class CountsNCL:
    """A stand-in for NCL's itinerary and cabin/availability calls (tools/fetch_counts.py). Each
    category has its own cabins (made up, spread over decks and locations); a call for a category
    at N guests answers with it and every pricier category of its broad type at N guests (prices
    from the price file), cabins listed cheapest first per deck and cut at 15, as NCL does
    (NOTES.md, "Cabin counts" and "Solo travelers (5.4.0)"). Solo cabins as in the probe of
    2026-11-15: Getaway IT 1 cabin on Mid deck 5, 2 on Forward deck 9, 7 on Forward deck 5.
    misorder: (code, deck) where another code is listed first; full: a code with 15 cabins on one deck."""

    def __init__(self, prices, misorder=None, full=None):
        self.prices, self.calls, self.misorder, self.full = prices, [], misorder, full
        self.cabins = {}
        locs = ["Forward", "Mid", "Aft"]
        for s in prices["sailings"]:
            for t in s["types"]:
                for i, c in enumerate(t["categories"]):
                    if c["guarantee"]:
                        continue
                    if c["code"] == "IT" and s["id"].startswith("getaway"):
                        cab = [("Mid", 5)] + [("Forward", 9)] * 2 + [("Forward", 5)] * 7
                    elif c["code"] == "T1":
                        cab = [("Forward", 12)] * 20 + [("Mid", 12)] * 9
                    else:
                        n = 3 + (sum(map(ord, c["code"])) % 17)
                        cab = [(locs[(i + k) % 3], 6 + (i + k) % 9) for k in range(n)]
                    if full == c["code"]:
                        cab = [("Forward", 5)] * 15 + [("Mid", 5)] * 3
                    self.cabins[(s["id"], c["code"])] = cab

    def __call__(self, url, body=None, raw=False, page=False):
        self.calls.append(url)
        assert not fp.FORBIDDEN.search(url)
        if "/itinerary/" in url:
            s = next(x for x in self.prices["sailings"] if x["package_id"] == url.split("packageId=")[1])
            i = s["ncl_ids"]
            ans = {"sailing": {"packageId": int(i["package_id"]), "sailStartDate": s["depart"] + "T00:00:00", "sailingId": int(i["sailing_id"])},
                   "ship": {"code": i["ship_code"]}, "destinations": [{"code": "X"}], "duration": s["nights"]}
            return (ans, json.dumps(ans).encode()) if raw else ans
        assert url == fp.CABIN_AVAILABILITY_URL
        f = body["stateroomSearchFilter"]
        s = next(x for x in self.prices["sailings"] if x["package_id"] == f["sailing"]["packageId"])
        g, code = str(f["numberOfGuests"]), f["pricedCategoryCode"]
        t = next(t for t in s["types"] if t["code"] == f["stateroomTypeCode"])
        price = lambda c: c["by_guests"][g]["price_pp"]
        me = next(c for c in t["categories"] if c["code"] == code)
        inc = sorted([c for c in t["categories"] if not c["guarantee"] and c["by_guests"][g]["available"] and (c is me or price(c) > price(me))],
                     key=lambda c: (price(c), c is not me))
        locations = []
        for loc in ("Forward", "Mid", "Aft"):
            decks = {}
            for c in inc:
                for l, d in self.cabins[(s["id"], c["code"])]:
                    if l == loc:
                        decks.setdefault(d, []).append({"pricedCategoryCode": c["code"], "deckNumber": d, "shipLocation": l, "cabinNumber": "REMOVED"})
            if not decks:
                continue
            listed = []
            for d, cabs in sorted(decks.items()):
                if self.misorder == (code, d):
                    cabs = [{"pricedCategoryCode": "IA", "deckNumber": d, "shipLocation": loc}] + cabs
                listed.append({"deckNumber": d, "numberOfCabins": min(len(cabs), 15), "cabins": cabs[:15]})
            locations.append({"name": loc, "numberOfCabins": sum(len(c) for c in decks.values()), "lowestPriceCategory": inc[0]["code"], "decks": listed})
        ans = {"results": {"availablePositionInShip": locations}}
        return (ans, json.dumps(ans).encode()) if raw else ans


def counts_run(ncl, folder, prices, previous=None, mode="full", guests=None, out=None):
    """One whole fetch_counts.py run (main) against the stand-in, no network. Returns the file it wrote."""
    pp, prev = os.path.join(folder, "prices.json"), os.path.join(folder, "counts.previous.json")
    out = out or os.path.join(folder, "counts.new.json")
    with open(pp, "w", encoding="utf-8") as f:
        json.dump(prices, f)
    if previous is not None:
        with open(prev, "w", encoding="utf-8") as f:
            json.dump(previous, f)
    elif os.path.exists(prev):
        os.remove(prev)
    keep = (fp.request, fp.log, fp.PAUSE_SECONDS, sys.argv)
    fp.request, fp.log = ncl, (lambda m: None)
    sys.argv = ["fetch_counts.py", "--prices", pp, "--previous", prev, "--out", out, "--mode", mode] + (["--guests", guests] if guests else [])
    try:
        fetch_counts.main()
    finally:
        fp.request, fp.log, fp.PAUSE_SECONDS, sys.argv = keep
    with open(out, encoding="utf-8") as f:
        return json.load(f)


def test_counts_one_guest():
    """Cabin counts at 1 guest (5.4.0): solo categories counted from their own call, regular
    categories copying their 2 guest count, the deck rules, light days, and --guests 1."""
    import check_counts
    folder = tempfile.mkdtemp(prefix="june-counts-")
    with open(os.path.join(os.path.dirname(TOOLS), "data", "prices.json"), encoding="utf-8") as f:
        real = json.load(f)
    p5 = schema5(real)
    solo_open = sum(1 for s in p5["sailings"] for t in s["types"] for c in t["categories"] if c["solo"] and c["by_guests"]["1"]["available"])
    check("counts: 6 solo categories open for 1 guest in the test prices (Getaway 4, Aura 2, as in the probe)", solo_open, 6)

    # A full sweep on schema 4 prices (no 1 guest) and on schema 5 prices: exactly 6 calls more.
    n4, n5 = CountsNCL(schema4(real)), CountsNCL(p5)
    c4 = counts_run(n4, folder, schema4(real))
    c5 = counts_run(n5, folder, p5)
    check("counts: 1 guest adds one call per open solo category (6), nothing else", len(n5.calls) - len(n4.calls), 6)
    check("counts: still 2 itinerary calls", sum("/itinerary/" in u for u in n5.calls), 2)
    check("counts: schema 4 prices, no 1 guest entries", any("1" in c["by_guests"] for cats in c4["sailings"].values() for c in cats.values()), False)
    check("counts: the full sweep file passes the format check", check_counts.check(c5), [])
    g = c5["sailings"]["getaway-2027-06-11"]
    check("counts: Getaway IT from its own cabin list (1 + 2 + 7)", (g["IT"]["by_guests"]["1"]["cabins_left"], g["IT"]["by_guests"]["1"]["reliable"]), (10, True))
    check("counts: IT open decks and locations from the 1 guest call", (g["IT"]["open_decks"], g["IT"]["open_locations"]), ([5, 9], ["forward", "midship"]))
    check("counts: Solo Studio from its location totals (no list limit: 20 on one deck)", g["T1"]["by_guests"]["1"]["cabins_left"], 29)
    check("counts: solo cabins only at 1 guest", sorted(g["IT"]["by_guests"]), ["1"])
    two = g["IA"]["by_guests"]["2"]
    check("counts: a regular cabin at 1 guest is its 2 guest count, same_as 2", g["IA"]["by_guests"]["1"], dict(two, same_as="2"))
    check("counts: copies are not listed again as unreliable", any(u["guests"] == "1" and u["category"] not in fp.SOLO_CODES for u in c5["unreliable"]), False)
    check("counts: no Guarantee entry", "IX" in g, False)
    check("counts: the Aura's sold out Solo Inside has no count", "1" in c5["sailings"]["aura-2027-06-14"].get("IT", {}).get("by_guests", {}), False)

    # The deck rules for solo cabins.
    mis = counts_run(CountsNCL(p5, misorder=("IT", 9)), folder, p5)
    e = mis["sailings"]["getaway-2027-06-11"]["IT"]["by_guests"]["1"]
    check("counts: another code before a solo cabin makes it unreliable", (e["cabins_left"], e["reliable"], "deck 9: another code is listed before" in e["why"]), (None, False, True))
    full = counts_run(CountsNCL(p5, full="IT"), folder, p5)
    e = full["sailings"]["getaway-2027-06-11"]["IT"]["by_guests"]["1"]
    check("counts: a full list (15) ending with the solo code makes it unreliable", (e["reliable"], "the list is full (15) and ends with IT" in (e["why"] or "")), (False, True))
    check("counts: unreliable solo counts are listed", any(u["category"] == "IT" and u["guests"] == "1" for u in full["unreliable"]), True)
    check("counts: a full list that goes on with pricier codes is fine (the probe's decks 9 and 5)", solo_count_ok(), True)

    # Light day: solo counts under 15 are checked again, others kept; copies follow "2".
    ln = CountsNCL(p5)
    light = counts_run(ln, folder, p5, previous=c5, mode="light")
    lg = light["sailings"]["getaway-2027-06-11"]
    check("counts, light day: IT (10) checked again, T1 (29) kept",
          (lg["IT"]["by_guests"]["1"]["checked_at"] == light["saved_at"], lg["T1"]["by_guests"]["1"] == g["T1"]["by_guests"]["1"]), (True, True))
    check("counts, light day: the file passes", check_counts.check(light), [])
    check("counts, light day: copies still equal the 2 guest entry", all(c["by_guests"]["1"] == dict(c["by_guests"]["2"], same_as="2")
          for c in lg.values() if "same_as" in c["by_guests"].get("1", {})), True)

    # Prices without usable 1 guest prices on the Getaway: no 1 guest counts there, no calls.
    nc = not_checked_1(real)
    ncn = CountsNCL(nc)
    cn = counts_run(ncn, folder, nc)
    check("counts, 1 guest not checked: no 1 guest entries on the Getaway", any("1" in c["by_guests"] for c in cn["sailings"]["getaway-2027-06-11"].values()), False)
    check("counts, 1 guest not checked: the Aura's 2 solo calls only", len(ncn.calls) - len(n4.calls), 2)

    # --guests 1: only the solo calls (and the itinerary calls), everything else as before, never in the data folder.
    gn = CountsNCL(p5)
    c4 = dict(c4, last_full_sweep="2026-11-14T10:22:19Z")   # an older full sweep, which a --guests 1 run must not move
    t1 = counts_run(gn, folder, p5, previous=c4, mode="full", guests="1", out=os.path.join(folder, "solo-test.json"))
    check("--guests 1: 2 itinerary calls and 6 solo calls, 8 in all", (len(gn.calls), sum("/itinerary/" in u for u in gn.calls)), (8, 2))
    check("--guests 1: every 2 to 5 guest count exactly as in the previous file",
          all({k: v for k, v in c["by_guests"].items() if k != "1"} == c4["sailings"][sid].get(code, {}).get("by_guests", {})
              for sid, cats in t1["sailings"].items() for code, c in cats.items() if code not in fp.SOLO_CODES), True)
    check("--guests 1: last_full_sweep unchanged, marked only_guests", (t1["last_full_sweep"], t1["only_guests"]), (c4["last_full_sweep"], [1]))
    check("--guests 1: passes the check as a test file", check_counts.check(t1, test_file=True), [])
    check("--guests 1: refused as data/counts.json by the workflow's check", any("only_guests" in x for x in check_counts.check(t1)), True)
    data_dir = os.path.join(os.path.dirname(TOOLS), "data")
    for name in ("counts.json", "counts.new.json", os.path.join("sub", "x.json")):
        target = os.path.join(data_dir, name)
        before = os.path.exists(target) and os.path.getmtime(target)
        calls = CountsNCL(p5)
        try:
            counts_run(calls, folder, p5, previous=c4, guests="1", out=target)
            refused = False
        except SystemExit as e:
            refused = "refusing to write" in str(e)
        check(f"--guests 1: refuses to write data/{name}, before any NCL call",
              (refused, len(calls.calls), (os.path.exists(target) and os.path.getmtime(target)) == before), (True, 0, True))
    with open(os.path.join(os.path.dirname(TOOLS), ".github", "workflows", "refresh-prices.yml"), encoding="utf-8") as f:
        check("the workflow never uses --guests", "--guests" in f.read(), False)

    # The format check on 1 guest entries.
    def broken(change):
        d = json.loads(json.dumps(c5))
        change(d["sailings"]["getaway-2027-06-11"])
        return check_counts.check(d)
    has = lambda errs, text: any(text in x for x in errs)
    check("counts format: a solo cabin with a 2 guest count fails", has(broken(lambda s: s["IT"]["by_guests"].update({"2": s["IA"]["by_guests"]["2"]})), "1 guest only"), True)
    check("counts format: a regular cabin's own 1 guest count fails",
          has(broken(lambda s: s["IA"]["by_guests"]["1"].pop("same_as")), "is a copy of its 2 guest count"), True)
    check("counts format: a copy that differs from 2 guests fails",
          has(broken(lambda s: s["IA"]["by_guests"]["1"].update(checked_at="2026-01-01T00:00:00Z")), "must equal the 2 guest entry"), True)
    check("counts format: same_as at 3 guests fails",
          has(broken(lambda s: s["IA"]["by_guests"]["3"].update(same_as="2")), "same_as is only"), True)


def solo_count_ok():
    """fetch_counts.solo_count on the probe's real Getaway IT answer (decks with 15 listed, IT first)."""
    r = saved("cabin_availability_getaway_IT_1_2026-11-15")
    locs = r["results"]["availablePositionInShip"]
    lists = [(l["name"], d.get("deckNumber") or d.get("number"), [c["pricedCategoryCode"] for c in d.get("cabins") or []]) for l in locs for d in l.get("decks") or []]
    count, why = fetch_counts.solo_count({"foreign": [], "totals": {}, "lists": lists}, "IT", alone=False)
    return count == 10 and why is None


def test_family_checks():
    """Release check (5.2.0): the family alerts Worker's preview address must be off to merge."""
    import check_release
    on, off = 'const TEST_ORIGIN = "https://raw.githack.com";', 'const TEST_ORIGIN = "";'
    page = lambda api, key: f'const FAMILY_API = "{api}"; const TURNSTILE_SITE_KEY = "{key}";'
    ok = page("https://cruise-family-alerts.example.workers.dev", "0x4AAAAAAA")
    check("release check: TEST_ORIGIN off and both page settings set", check_release.family_checks(off, ok), [])
    check("release check: TEST_ORIGIN off and neither set", check_release.family_checks(off, page("", "")), [])
    check("release check: TEST_ORIGIN on fails", any("TEST_ORIGIN is \"https://raw.githack.com\"" in x for x in check_release.family_checks(on, ok)), True)
    check("release check: no TEST_ORIGIN line fails", any("is missing" in x for x in check_release.family_checks("", ok)), True)
    check("release check: only one of the page settings fails", any("both be set" in x for x in check_release.family_checks(off, page("https://a.workers.dev", ""))), True)
    check("release check: a trailing slash fails", any("trailing slash" in x for x in check_release.family_checks(off, page("https://a.workers.dev/", "k"))), True)
    check("release check: http fails", any("not an https" in x for x in check_release.family_checks(off, page("http://a.workers.dev", "k"))), True)
    with open(os.path.join(os.path.dirname(TOOLS), "tools", "family-alerts", "worker.js"), encoding="utf-8") as f:
        check("release check: the Worker file has the TEST_ORIGIN line", bool(re.search(r'^const TEST_ORIGIN = "[^"]*";$', f.read(), re.M)), True)


def test_no_em_dashes():
    """Owner's rule: no em dashes anywhere (code, docs, page text, steps)."""
    root = os.path.dirname(TOOLS)
    files = subprocess.run(["git", "-C", root, "ls-files"], capture_output=True, text=True).stdout.split()
    found = []
    for name in files:
        if name.startswith("data/") or not name.endswith((".py", ".md", ".html", ".yml", ".js", ".mjs", ".gs", ".sql", ".txt", ".json")):
            continue
        try:
            with open(os.path.join(root, name), encoding="utf-8") as f:
                if EM_DASH in f.read():
                    found.append(name)
        except (OSError, UnicodeDecodeError):
            continue
    check("No em dashes in any tracked file", found, [])


if __name__ == "__main__":
    test_decide()
    test_counts_cadence()
    test_hold_signal()
    test_request_guards()
    test_request_redirects()
    test_find_sailing()
    test_check_prices_ids()
    test_missing_numbers()
    test_kids_sail_free()
    test_florida_plan_and_format()
    test_florida_runs()
    test_florida_clone_guard()
    test_offers()
    test_payment()
    test_one_guest()
    test_saved_one_guest()
    test_counts_one_guest()
    test_eastern_dates()
    test_family_checks()
    test_no_em_dashes()
    print(f"\n{'All tests passed' if not FAILED else str(len(FAILED)) + ' FAILED: ' + '; '.join(FAILED)}")
    sys.exit(1 if FAILED else 0)
