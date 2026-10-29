#!/usr/bin/env python3
"""Format check for the price data file the page reads (data/prices.json).

  python3 tools/check_prices.py data/prices.new.json

Exits 1 and lists every problem when the file is malformed, a sailing is missing,
or a formula cross check failed. The refresh workflow runs this on the new file
before it replaces the old one.
"""
import datetime as dt
import json
import re
import sys

EXPECTED_SAILINGS = {"getaway-2027-06-11", "aura-2027-06-14"}
GUEST_KEYS = ["2", "3", "4", "5"]
MATCH_KEYS = {"studio", "inside", "oceanview", "balcony", "mini_suite", "suite", "haven"}
PERCENT_RULE = "10% of the cruise fare"
PER_GUEST_RULE = "same deposit per guest"
PAYMENT_KEYS = {"source", "final_payment_due", "standard_deposit_per_guest", "standard_deposit_checked_at", "by_guests", "deposit_offer"}
DEPOSIT_ENTRY_KEYS = {"deposit", "deposit_type", "deposit_category", "due_hours", "as_of", "why"}


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_date(v):
    try:
        dt.date.fromisoformat(v)
        return True
    except (TypeError, ValueError):
        return False


def is_money(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0


def check(data, allow_schema_3=False):
    """Problems with a price file. Every file fetch_prices.py writes is schema 4.

    allow_schema_3: only for the release check (tools/check_release.py) on the committed file,
    which stays the schema 3 file written before 5.2.0 until the first refresh on main after
    the merge. Such a file is checked as before (no payment, deposit_rules or deposit checks).
    The refresh workflow's check of each new file never allows it.
    """
    if not isinstance(data, dict):
        return ["the file is not a JSON object"]
    old = allow_schema_3 and data.get("schema_version") == 3
    errors = []
    err = errors.append

    if data.get("schema_version") != 4 and not old:
        err("schema_version must be 4")
    warnings = data.get("warnings")
    rate_warnings = data.get("rate_warnings")
    if not isinstance(warnings, list) or not all(isinstance(w, str) for w in warnings) \
            or not isinstance(rate_warnings, list) or not all(isinstance(w, str) for w in rate_warnings):
        err("warnings and rate_warnings must be lists of text")
        warnings, rate_warnings = [], []

    def warned(ship, word):
        """A missing number (null) is allowed only with a warning naming the ship and the item."""
        return any(w.startswith(ship + ":") and word in w.lower() for w in warnings)
    try:
        dt.datetime.strptime(data.get("saved_at", ""), "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        err("saved_at must look like 2026-10-07T10:17:00Z")
    if data.get("guest_counts") != [2, 3, 4, 5]:
        err("guest_counts must be [2, 3, 4, 5]")

    checks = data.get("checks")
    if not isinstance(checks, dict) or not isinstance(checks.get("formula"), list) \
            or not isinstance(checks.get("extra_guest_mismatches"), list):
        err("checks.formula and checks.extra_guest_mismatches must be lists")
    else:
        if len(checks["formula"]) != len(EXPECTED_SAILINGS) * len(GUEST_KEYS):
            err("checks.formula must have one entry per sailing per party size")
        for c in checks["formula"]:
            if c.get("ok") is not True:
                err(f"formula cross check failed: {c}")
        ages = checks.get("ages")
        if not isinstance(ages, list) or len(ages) != len(EXPECTED_SAILINGS):
            err("checks.ages must have one entry per sailing")
        else:
            for c in ages:
                # ok None: NCL's gratuities weren't found today; the sailing's gratuities are null
                # (checked below) and the entry says why.
                if c.get("ok") is False or (c.get("ok") is None and not c.get("why")) or c.get("ok") not in (True, False, None):
                    err(f"age cross check failed: {c}")

    # Deposits (schema 4): a deposit check that failed is allowed (logged), but then the number it
    # checks must be empty (null): the Suite and Haven rule, or that ship's standard deposit.
    deposit_checks = []
    if not old:
        deposit_checks = (checks or {}).get("deposits") if isinstance(checks, dict) else None
        if not isinstance(deposit_checks, list):
            err("checks.deposits must be a list")
            deposit_checks = []
        for c in deposit_checks:
            if not isinstance(c, dict) or c.get("sailing") not in EXPECTED_SAILINGS or c.get("rule") not in (PERCENT_RULE, PER_GUEST_RULE) \
                    or not isinstance(c.get("ok"), bool) or not is_money(c.get("deposit")) or not is_money(c.get("expected")):
                err(f"checks.deposits entry is malformed: {c}")
        rules = data.get("deposit_rules")
        if not isinstance(rules, dict):
            err("deposit_rules is missing")
        else:
            pct = rules.get("percent_of_fare")
            if pct is None:
                if not any(w.startswith("Deposits:") for w in warnings):
                    err("deposit_rules.percent_of_fare is empty without a warning")
                if rules.get("confirmed_on") is not None:
                    err("deposit_rules: confirmed_on must be null when the rule is empty")
            elif not is_money(pct) or pct > 100:
                err("deposit_rules.percent_of_fare must be a percentage or null")
            elif not is_date(rules.get("confirmed_on")) or not rules.get("confirmed_by"):
                err("deposit_rules needs confirmed_on and confirmed_by")
            if any(isinstance(c, dict) and c.get("rule") == PERCENT_RULE and c.get("ok") is False for c in deposit_checks) and pct is not None:
                err("a Suite or Haven deposit check failed but deposit_rules.percent_of_fare is set")
            if rules.get("suite_haven_types") != ["SUITE", "HAVEN"]:
                err("deposit_rules.suite_haven_types must be SUITE and HAVEN")
            if not str(rules.get("source", "")).startswith("https://www.ncl.com/"):
                err("deposit_rules.source must be an NCL page")

    rates = data.get("rates")
    if not isinstance(rates, dict):
        err("rates block is missing")
    else:
        need = {"free_at_sea_plus": ["adult_per_day", "child_per_day"],
                "open_bar": ["per_day_2_to_5_nights", "per_day_6_plus_nights", "soda_per_day"],
                "service_charge": ["suite_haven_per_night", "standard_per_night"]}
        for key, fields in need.items():
            if key not in rates:
                err(f"rates.{key} is missing")
                continue
            r = rates[key]
            if r is None:
                # Not found on NCL today and no earlier rate to keep: allowed only with a warning.
                if not any(w.startswith(key + ":") for w in rate_warnings):
                    err(f"rates.{key} is empty without a warning")
                continue
            if not isinstance(r, dict):
                err(f"rates.{key} must be an object or null")
                continue
            for f in fields:
                if not isinstance(r.get(f), (int, float)) or isinstance(r.get(f), bool) or r[f] <= 0:
                    err(f"rates.{key}.{f} must be a positive number")
            if not str(r.get("source", "")).startswith("https://www.ncl.com/"):
                err(f"rates.{key}.source must be an NCL page")
            try:
                dt.date.fromisoformat(r.get("checked_at", ""))
            except (TypeError, ValueError):
                err(f"rates.{key}.checked_at must be a date")
        sc = rates.get("service_charge")
        if isinstance(sc, dict) and (not is_int(sc.get("min_age")) or not isinstance(sc.get("suite_haven_types"), list)):
            err("rates.service_charge needs min_age and suite_haven_types")

    sailings = data.get("sailings")
    if not isinstance(sailings, list):
        return errors + ["sailings must be a list"]
    ids = [s.get("id") for s in sailings if isinstance(s, dict)]
    for missing in sorted(EXPECTED_SAILINGS - set(ids)):
        err(f"sailing {missing} is missing")
    if len(ids) != len(set(ids)):
        err("a sailing appears twice")

    for s in sailings:
        p = f"sailing {s.get('id', '?')}"
        for k in ("ship", "ship_short", "itinerary_code", "package_id", "url", "source"):
            if not isinstance(s.get(k), str) or not s.get(k):
                err(f"{p}: {k} is missing")
        for k in ("depart", "return", "saved_at"):
            if not is_date(s.get(k)):
                err(f"{p}: {k} must be a YYYY-MM-DD date")
        # NCL's ids, looked up on every run (fetch_prices.find_sailing), never typed in.
        ids = s.get("ncl_ids")
        if not isinstance(ids, dict) or not all(isinstance(ids.get(k), str) and ids[k] for k in ("itinerary_code", "package_id", "sailing_id", "ship_code", "found_on", "checked_at")):
            err(f"{p}: ncl_ids needs itinerary_code, package_id, sailing_id, ship_code, found_on and checked_at")
        elif ids["package_id"] != s.get("package_id") or ids["itinerary_code"] != s.get("itinerary_code"):
            err(f"{p}: ncl_ids does not match package_id and itinerary_code")
        elif not re.fullmatch(r"\d+", ids["package_id"]) or not re.fullmatch(r"\d+", ids["sailing_id"]):
            err(f"{p}: ncl_ids package_id and sailing_id must be digits")
        elif ids["found_on"] == "previous run" and not any(s.get("ship_short", "?") in w and "previous run" in w for w in data.get("warnings") or []):
            err(f"{p}: ids from the previous run without a warning")
        if not is_int(s.get("nights")) or s.get("nights", 0) < 1:
            err(f"{p}: nights must be a positive whole number")
        tx = s.get("taxes_per_guest")
        if tx is None:
            if not warned(s.get("ship_short", "?"), "tax"):
                err(f"{p}: taxes_per_guest is empty without a warning")
        elif not isinstance(tx, (int, float)) or isinstance(tx, bool) or tx <= 0:
            err(f"{p}: taxes_per_guest must be a positive number or null")
        grat = s.get("gratuities")
        age = next((c for c in ((checks or {}).get("ages") or []) if isinstance(c, dict) and c.get("sailing") == s.get("id")), {})
        if grat is None:
            if not warned(s.get("ship_short", "?"), "gratuities"):
                err(f"{p}: gratuities are empty without a warning")
            if age.get("ok") is not None:
                err(f"{p}: gratuities are empty but the age check says ok {age.get('ok')}")
            grat = {"open_bar": {"title": "-", "per_guest": 0, "soda_under_21_position_2": 0}, "specialty_dining": {"title": "-", "per_guest": 0}}
        elif age.get("ok") is None and age:
            err(f"{p}: the age check found no gratuities, but gratuities are set")
        for k in ("open_bar", "specialty_dining"):
            g = grat.get(k) if isinstance(grat, dict) else None
            if not isinstance(g, dict) or not g.get("title") or not isinstance(g.get("per_guest"), (int, float)) or g["per_guest"] < 0:
                err(f"{p}: gratuities.{k} needs a title and a per_guest amount")
        soda = (grat.get("open_bar") or {}).get("soda_under_21_position_2") if isinstance(grat, dict) else None
        if not isinstance(soda, (int, float)) or soda < 0:
            err(f"{p}: gratuities.open_bar.soda_under_21_position_2 must be a number")
        if "kids_sail_free" not in s:
            err(f"{p}: kids_sail_free is missing (null when NCL doesn't list the offer)")
        ksf = s.get("kids_sail_free")
        if ksf is not None and (not isinstance(ksf, dict) or not ksf.get("title") or not isinstance(ksf.get("types"), list)
                                or not all(isinstance(t, str) for t in ksf["types"]) or not isinstance(ksf.get("codes", []), list)):
            err(f"{p}: kids_sail_free must be null or have a title and a list of types")
        if not old:
            check_payment(s, p, deposit_checks, warned, err)
        if not isinstance((s.get("terminal") or {}).get("text"), str):
            err(f"{p}: terminal.text is missing")
        ports = s.get("ports")
        if not isinstance(ports, list) or len(ports) != (s.get("nights") or 0) + 1:
            err(f"{p}: ports must have one entry per day (nights + 1)")
        elif any(not is_date(d.get("date")) for d in ports):
            err(f"{p}: every port day needs a date")

        ps = s.get("party_sizes")
        if not isinstance(ps, dict) or sorted(ps) != GUEST_KEYS:
            err(f"{p}: party_sizes must have the keys 2, 3, 4, 5")
        else:
            if not any(v.get("updated") is True for v in ps.values()):
                err(f"{p}: no party size was updated")
            for g, v in ps.items():
                if not isinstance(v.get("updated"), bool):
                    err(f"{p}: party_sizes.{g}.updated must be true or false")
                try:
                    as_of = dt.datetime.strptime(v.get("as_of", ""), "%Y-%m-%dT%H:%M:%SZ")
                    saved = dt.datetime.strptime(data.get("saved_at", ""), "%Y-%m-%dT%H:%M:%SZ")
                    if (saved - as_of).total_seconds() > 3 * 86400:
                        err(f"{p}: prices for {g} guests are more than 3 days old")
                except (TypeError, ValueError):
                    err(f"{p}: party_sizes.{g}.as_of must be a time")
                if v.get("updated") is False and not v.get("why"):
                    err(f"{p}: party_sizes.{g} is not updated but has no why")

        types = s.get("types")
        if not isinstance(types, list) or not types:
            err(f"{p}: types is empty")
            continue
        available_for = {g: False for g in GUEST_KEYS}
        for t in types:
            tp = f"{p} type {t.get('code', '?')}"
            if not t.get("code") or not t.get("title"):
                err(f"{tp}: code and title are required")
            if t.get("match") not in MATCH_KEYS:
                err(f"{tp}: match must be one of {sorted(MATCH_KEYS)}")
            cats = t.get("categories")
            if not isinstance(cats, list):
                err(f"{tp}: categories must be a list")
                continue
            for c in cats:
                cp = f"{tp} category {c.get('code', '?')}"
                if not c.get("code") or not c.get("title"):
                    err(f"{cp}: code and title are required")
                for k in ("guarantee", "solo"):
                    if not isinstance(c.get(k), bool):
                        err(f"{cp}: {k} must be true or false")
                if c.get("capacity") is not None and (not is_int(c["capacity"]) or c["capacity"] < 1):
                    err(f"{cp}: capacity must be a positive whole number or null")
                if not isinstance(c.get("description"), str) or not c["description"].startswith(c.get("title") or "\0"):
                    err(f"{cp}: description must start with the category title")
                decks = c.get("decks")
                if decks is not None and (not isinstance(decks, list) or not decks or not all(is_int(d) for d in decks)):
                    err(f"{cp}: decks must be a list of deck numbers or null")
                locs = c.get("location")
                if locs is not None and (not isinstance(locs, list) or not set(locs) <= {"forward", "midship", "aft"}):
                    err(f"{cp}: location must be a list of forward, midship, aft or null")
                if (decks or locs) and not c.get("details_source"):
                    err(f"{cp}: decks or location without a details_source")
                if c.get("guarantee") and (decks or locs):
                    err(f"{cp}: guarantee cabins must not list decks or a location")
                if c.get("size") is not None and not isinstance(c["size"], str):
                    err(f"{cp}: size must be text or null")
                if not isinstance(c.get("shares_ncl_description_with"), list):
                    err(f"{cp}: shares_ncl_description_with must be a list")
                bg = c.get("by_guests")
                if not isinstance(bg, dict) or sorted(bg) != GUEST_KEYS:
                    err(f"{cp}: by_guests must have exactly the keys 2, 3, 4, 5")
                    continue
                for g in GUEST_KEYS:
                    e = bg[g]
                    ep = f"{cp} at {g} guests"
                    if not isinstance(e.get("available"), bool) or not isinstance(e.get("sold_out"), bool):
                        err(f"{ep}: available and sold_out must be true or false")
                        continue
                    if e["available"]:
                        pp = e.get("price_pp")
                        if not isinstance(pp, (int, float)) or isinstance(pp, bool) or pp <= 0:
                            err(f"{ep}: price_pp must be a positive number")
                        elif not is_int(e.get("cabin_total")) or abs(e["cabin_total"] - pp * int(g)) > 0.5 + 0.01 * int(g):
                            err(f"{ep}: cabin_total must be price_pp x {g}, rounded to whole dollars")
                        if g != "2" and bg["2"].get("available") and not is_int(e.get("added_vs_2")):
                            err(f"{ep}: added_vs_2 is missing")
                        if not c.get("solo"):
                            available_for[g] = True
                        if "cabins_left" in e or "count_reliable" in e:
                            err(f"{ep}: cabin counts belong in data/counts.json, not in prices")
                    else:
                        if "price_pp" in e:
                            err(f"{ep}: not available but has a price")
                        if not isinstance(e.get("reason"), str) or not e["reason"]:
                            err(f"{ep}: unavailable without a reason")
        for g, ok in available_for.items():
            if not ok:
                err(f"{p}: no cabin is available for {g} guests")
    return errors


def check_payment(s, p, deposit_checks, warned, err):
    """A sailing's payment block (schema 4): deposits and the final payment date from NCL's price
    summaries. Each empty (null) number needs a warning naming the ship."""
    ship = s.get("ship_short", "?")
    pay = s.get("payment")
    if not isinstance(pay, dict) or set(pay) != PAYMENT_KEYS:
        err(f"{p}: payment must have exactly {sorted(PAYMENT_KEYS)}")
        return
    if pay["source"] != "NCL price-summary paymentOptions":
        err(f"{p}: payment.source must be NCL price-summary paymentOptions")
    due = pay["final_payment_due"]
    if due is None:
        if not warned(ship, "final payment"):
            err(f"{p}: payment.final_payment_due is empty without a warning")
    elif not is_date(due) or (is_date(s.get("depart")) and due >= s["depart"]):
        err(f"{p}: payment.final_payment_due must be a date before the sail date")
    per = pay["standard_deposit_per_guest"]
    if per is None:
        if pay["standard_deposit_checked_at"] is not None:
            err(f"{p}: payment.standard_deposit_checked_at must be null when the deposit is empty")
        if not warned(ship, "deposit"):
            err(f"{p}: payment.standard_deposit_per_guest is empty without a warning")
    elif not is_money(per) or not is_date(pay["standard_deposit_checked_at"]):
        err(f"{p}: payment.standard_deposit_per_guest must be a positive number with a checked_at date")
    if per is not None and any(isinstance(c, dict) and c.get("sailing") == s.get("id") and c.get("rule") == PER_GUEST_RULE
                               and c.get("ok") is False for c in deposit_checks):
        err(f"{p}: a deposit per guest check failed but payment.standard_deposit_per_guest is set")
    bg = pay["by_guests"]
    if not isinstance(bg, dict) or sorted(bg) != GUEST_KEYS:
        err(f"{p}: payment.by_guests must have exactly the keys 2, 3, 4, 5")
    else:
        for g, e in bg.items():
            ep = f"{p}: payment.by_guests.{g}"
            if not isinstance(e, dict) or set(e) != DEPOSIT_ENTRY_KEYS:
                err(f"{ep} must have exactly {sorted(DEPOSIT_ENTRY_KEYS)}")
                continue
            if e["deposit"] is None:
                if not e["why"] or not warned(ship, "deposit"):
                    err(f"{ep}: an empty deposit needs a why and a warning")
                if e["due_hours"] is not None:
                    err(f"{ep}: due_hours without a deposit")
            elif not is_money(e["deposit"]) or not isinstance(e["deposit_type"], str) or not isinstance(e["deposit_category"], str):
                err(f"{ep}: deposit must be a positive number with its cabin type and category")
            if e["due_hours"] is not None and (not isinstance(e["due_hours"], int) or isinstance(e["due_hours"], bool) or e["due_hours"] < 1):
                err(f"{ep}: due_hours must be a positive whole number or null")
            try:
                dt.datetime.strptime(e["as_of"] or "", "%Y-%m-%dT%H:%M:%SZ")
            except (TypeError, ValueError):
                err(f"{ep}: as_of must be a time")
    offer = pay["deposit_offer"]
    if offer is not None and (not isinstance(offer, dict) or not offer.get("title") or not isinstance(offer.get("types"), list)
                              or not isinstance(offer.get("codes"), list)):
        err(f"{p}: payment.deposit_offer must be null or have a title, types and codes")


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
