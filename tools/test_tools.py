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
"""
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS)
import decide_run  # noqa: E402
import fetch_counts  # noqa: E402
import fetch_prices as fp  # noqa: E402

TEST_DATA = os.path.join(TOOLS, "test_data")

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


SAVED_PRICE_SUMMARIES = sorted(f[:-5] for f in os.listdir(TEST_DATA) if f.startswith("price_summary_getaway_"))


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
    if old.get("schema_version") == 2:
        check("release check accepts the committed schema 2 file", check_prices.check(old, allow_schema_2=True), [])
        check("the refresh's check of a new file never accepts schema 2", "schema_version must be 3" in check_prices.check(old), True)
    new = json.loads(json.dumps(old))
    new["schema_version"], new["warnings"] = 3, []
    for s in new["sailings"]:
        s["ncl_ids"] = {"itinerary_code": s["itinerary_code"], "package_id": s["package_id"], "sailing_id": "60533",
                        "ship_code": s["ship_short"].upper(), "found_on": f"https://www.ncl.com/cruises/{s['itinerary_code']}",
                        "checked_at": "2026-10-15T10:20:00Z"}
        s.setdefault("kids_sail_free", None)
    check("schema 3 file with ncl_ids passes", check_prices.check(new), [])
    bad = json.loads(json.dumps(new))
    bad["sailings"][0]["ncl_ids"]["package_id"] = "1"
    check("ncl_ids that don't match the sailing fail", any("does not match" in e for e in check_prices.check(bad)), True)
    prev = json.loads(json.dumps(new))
    prev["sailings"][1]["ncl_ids"]["found_on"] = "previous run"
    check("ids from the previous run without a warning fail", any("without a warning" in e for e in check_prices.check(prev)), True)
    prev["warnings"] = ["Aura: could not find the sailing on NCL's cruise page (x); tried the previous run's ids"]
    check("ids from the previous run with the warning pass", check_prices.check(prev), [])


def schema3(data):
    """A schema 3 copy of a price file (adds warnings and ncl_ids when the file is still schema 2)."""
    d = json.loads(json.dumps(data))
    d["schema_version"] = 3
    d.setdefault("warnings", [])
    for s in d["sailings"]:
        s.setdefault("kids_sail_free", None)
        s.setdefault("ncl_ids", {"itinerary_code": s["itinerary_code"], "package_id": s["package_id"], "sailing_id": "1",
                                 "ship_code": s["ship_short"].upper(), "found_on": "https://www.ncl.com/cruises/x",
                                 "checked_at": "2026-10-15T10:20:00Z"})
    return d


def null_copy(data):
    """The test copy for "Not found on NCL today": Getaway taxes and gratuities, and every rate,
    null, each with the warning fetch_prices.py would write."""
    d = schema3(data)
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
        real = schema3(json.load(f))
    check("format check: kids_sail_free null passes", check_prices.check(real), [])
    d = json.loads(json.dumps(real))
    d["sailings"][0]["kids_sail_free"] = dict(k, checked_at="2026-10-15T10:20:00Z")
    check("format check: kids_sail_free from NCL passes", check_prices.check(d), [])
    for bad in ({"title": "", "types": []}, {"title": "Kids Sail Free"}, {"title": "Kids Sail Free", "types": "INSIDE"}, "yes"):
        d["sailings"][0]["kids_sail_free"] = bad
        check(f"format check: kids_sail_free {bad!r} rejected", any("kids_sail_free must be null" in e for e in check_prices.check(d)), True)
    del d["sailings"][0]["kids_sail_free"]
    check("format check: kids_sail_free missing from a schema 3 file rejected", any("kids_sail_free is missing" in e for e in check_prices.check(d)), True)


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
    print(f"\n{'All tests passed' if not FAILED else str(len(FAILED)) + ' FAILED: ' + '; '.join(FAILED)}")
    sys.exit(1 if FAILED else 0)
