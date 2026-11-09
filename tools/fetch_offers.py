#!/usr/bin/env python3
"""CruiseNext offer watch (5.2.0, any multi-credit offer since 5.3.0): reads NCL's CruiseNext
page once a day and saves the multi-credit banner (DoubleUp, TripleUp, QuadUp).

  python3 tools/fetch_offers.py --previous data/offers.json --out data/offers.new.json --issue-dir DIR
  python3 tools/fetch_offers.py --mark-reported data/offers.new.json

1 NCL page load per run (GET https://www.ncl.com/cruise-deals/cruisenext, through
fetch_prices.request(): the address guard applies, tried once, no cookies). Runs in the
"refresh" job of .github/workflows/refresh-prices.yml, before the prices.

What is saved (data/offers.json, schema 2, checked by tools/check_offers.py): whether a
multi-credit banner ("Limited-Time Offer: DoubleUp!", "TripleUp!", "QuadUp!", with or without
"!", spaces or hyphens) is on the page, its name, its exact text, the number of credits (the
heading's number and the text's "apply TWO/THREE/FOUR ... credits" must agree), the cabin types
and the time before sailing read from that text, and the last change (old and new state, the
Eastern date, and whether its GitHub issue has been opened). Wording that can't be read is saved
as null with a warning; the page then offers one credit (never guessed). Schema 1 files (the
"doubleup" key, 5.2.0) are still read as the previous file.

5.2.0 matched only "DoubleUp" headings, so on 2026-11-06 it recorded NCL's switch to TripleUp as
"ended". ONE_TIME_FIX turns exactly that schema 1 state into a "changed" issue (DoubleUp to
TripleUp) on the first run that reads a multi-credit offer. Remove it once main has a schema 2
file (NOTES.md, "CruiseNext offer watch").

A page that can't be read (an error, a page without NCL's CruiseNext terms, or an "apply
TWO ... CruiseNext" sentence under a heading the watch doesn't know) keeps the previous state
with read_ok false and a warning. It never fails the price run and never opens an issue: only
a page that was read decides that the banner appeared, changed or ended.

Issues: when the state differs from the previous file's (or there is no previous state: the
"CruiseNext offer watch started" issue), --issue-dir gets title.txt, body.md and marker.txt. The
workflow (main only) searches the repo's issues for the marker, opens one if none has it, then
runs --mark-reported. A change whose issue couldn't be opened stays unreported and is tried
again on the next run. The marker comes from the old state, the new state and the date the old
state began, so it is the same on every retry of one change and different for every change.
"""
import argparse
import datetime as dt
import hashlib
import html
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_prices as fp  # noqa: E402

SCHEMA_VERSION = 2
CRUISENEXT_URL = "https://www.ncl.com/cruise-deals/cruisenext"
REPO_OWNER = "DASatizabal"
TYPE_ORDER = ["STUDIO", "INSIDE", "OCEANVIEW", "BALCONY", "MINISUITE", "SUITE", "HAVEN"]
TYPE_NAMES = {"STUDIO": "Studio", "INSIDE": "Inside", "OCEANVIEW": "Oceanview", "BALCONY": "Balcony",
              "MINISUITE": "Club Balcony Suite", "SUITE": "Suite", "HAVEN": "The Haven"}
# Longest names first, so "club balcony suite" is never read as "balcony" or "suite".
NAME_TO_TYPE = [
    ("club balcony suites", "MINISUITE"), ("club balcony suite", "MINISUITE"), ("club balcony", "MINISUITE"),
    ("mini-suites", "MINISUITE"), ("mini-suite", "MINISUITE"), ("mini suite", "MINISUITE"),
    ("the haven", "HAVEN"), ("haven", "HAVEN"), ("suites", "SUITE"), ("suite", "SUITE"),
    ("balconies", "BALCONY"), ("balcony", "BALCONY"), ("ocean view", "OCEANVIEW"), ("oceanview", "OCEANVIEW"),
    ("inside", "INSIDE"), ("interior", "INSIDE"), ("studios", "STUDIO"), ("studio", "STUDIO"),
]
HEADING = re.compile(r"<h([1-6])\b[^>]*>(.*?)</h\1>", re.I | re.S)
PARAGRAPH = re.compile(r"<p\b[^>]*>(.*?)</p>", re.I | re.S)
# Multi-credit offer names: DoubleUp, Double Up, Double-Up, TripleUp, QuadUp, QuadrupleUp, with
# or without "!". The word gives the heading's number of credits.
MULTI = re.compile(r"\b(double|triple|quadruple|quad)\s*-?\s*up\b\s*!?", re.I)
HEADING_CREDITS = {"double": 2, "triple": 3, "quad": 4, "quadruple": 4}
MIN_CREDITS, MAX_CREDITS = 2, 4
# The number in the offer text: "apply THREE CruiseNext, CruiseNext Haven, CruiseNext Lite credits".
APPLY = re.compile(r"\bapply\s+(?:up\s+to\s+)?([a-z]+|\d+)\s+(?:\(\d+\)\s+)?CruiseNext\b", re.I)
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
FOOTNOTE = re.compile(r"\s*<(?:sub|sup|small)\b", re.I)
NEAR = 4000   # characters after the heading in which the offer paragraph must start

# One-time fix (5.3.0, owner's rule 2026-11-07). 5.2.0 only matched "DoubleUp" headings, so on
# 2026-11-06 it saved NCL's switch to TripleUp as "ended". Only a schema 1 previous file whose
# last change is exactly that one ("ended" on 2026-11-06 with this old text, nothing listed now),
# followed by a page that shows a multi-credit offer, is reported as a change from DoubleUp.
# Every other schema 1 "ended" is handled normally. Remove once main has a schema 2 file.
ONE_TIME_FIX = {"on": "2026-11-06", "name": "DoubleUp!", "credits": 2,
                "old_text": ("Book a Balcony and above stateroom on any sailing at least 90 days prior to sailing "
                             "and apply TWO CruiseNext, CruiseNext Haven, CruiseNext Lite credits.*")}


class Unreadable(Exception):
    pass


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def plain(fragment):
    """HTML fragment to one line of text, as a reader sees it."""
    text = re.sub(r"<[^>]+>", " ", fragment)
    text = html.unescape(text).replace(" ", " ")
    return re.sub(r"\s+", " ", text).strip()


def read_banner(page):
    """(title, text) of the multi-credit banner, or (None, None) when the page has none.

    Raises Unreadable when the page doesn't look like NCL's CruiseNext page (it must carry the
    CruiseNext credit terms), a multi-credit heading has no text after it, or the page offers
    more than one credit ("apply TWO ... CruiseNext") under a heading the watch doesn't know
    (so a new offer name is never read as the offer ending).
    """
    whole = plain(page)
    if "CruiseNext" not in whole or not re.search(r"per stateroom", whole, re.I):
        raise Unreadable("the page has no CruiseNext credit terms (moved, blocked or changed)")
    for m in HEADING.finditer(page):
        title = plain(m.group(2))
        if not MULTI.search(title):
            continue
        # The offer is the first paragraph right after the heading (NCL's text component next
        # to its title component, about 900 characters on). A footnote (<sub> or <sup>), a
        # paragraph far away or one after the next heading is never read as the offer.
        nxt = HEADING.search(page, m.end())
        stop = min(nxt.start() if nxt else len(page), m.end() + NEAR)
        p = PARAGRAPH.search(page, m.end(), stop)
        text = plain(p.group(1)) if p and not FOOTNOTE.match(p.group(1)) else ""
        if not text:
            raise Unreadable(f'the "{title}" heading has no offer text right after it')
        return title, text
    for n in APPLY.finditer(whole):
        if (number_of(n.group(1)) or 0) > 1:
            raise Unreadable(f'the page offers "apply {n.group(1)} CruiseNext" credits under a heading the watch '
                             "doesn't know (not DoubleUp, TripleUp or QuadUp)")
    return None, None


def number_of(word):
    word = word.strip().lower()
    return int(word) if word.isdigit() else NUMBER_WORDS.get(word)


def read_name(title):
    """The offer's name as NCL writes it in the heading, like "TripleUp!"."""
    m = MULTI.search(title or "")
    return m.group(0).strip() if m else None


def short_name(name):
    return (name or "").rstrip("!").strip()


def read_credits(title, text):
    """(credits, warning): the heading's number when the text says the same, else (None, why)."""
    m = MULTI.search(title or "")
    head = HEADING_CREDITS[m.group(1).lower()] if m else None
    found = [number_of(x.group(1)) for x in APPLY.finditer(text or "")]
    found = [n for n in found if n is not None]
    name = read_name(title) or "the offer"
    if not found:
        return None, (f"CruiseNext offer: could not read how many credits {name} allows from its text; "
                      "one credit is offered")
    if len(set(found)) > 1 or found[0] != head:
        said = " and ".join(str(n) for n in sorted(set(found)))
        return None, (f"CruiseNext offer: the heading {name} means {head} credits but the text says {said}; "
                      "how many credits is unclear, so one credit is offered")
    if not MIN_CREDITS <= head <= MAX_CREDITS:
        return None, (f"CruiseNext offer: how many credits {name} allows ({head}) is outside {MIN_CREDITS} to "
                      f"{MAX_CREDITS}; one credit is offered")
    return head, None


def read_types(text):
    """Cabin types the offer text names, or None when the wording isn't understood."""
    m = re.search(r"\bbook (?:an? )?(.+?) staterooms?\b", text, re.I)
    if not m:
        return None
    phrase = m.group(1).strip().lower()
    if phrase in ("any", "all"):
        return list(TYPE_ORDER)
    up = re.fullmatch(r"(.+?)\s+(?:and|or)\s+(?:above|higher|up)", phrase)
    if up:
        t = name_type(up.group(1))
        return TYPE_ORDER[TYPE_ORDER.index(t):] if t else None
    parts = [p for p in re.split(r"\s*,\s*|\s+or\s+|\s+and\s+", phrase) if p]
    types = [name_type(p) for p in parts]
    if not types or None in types:
        return None
    return [t for t in TYPE_ORDER if t in types]


def name_type(name):
    name = name.strip().lower()
    for words, t in NAME_TO_TYPE:
        if name == words:
            return t
    return None


def read_lead_time(text):
    """(min_days, min_months) before sailing; both None when the text gives neither."""
    d = re.search(r"at least (\d+) days? (?:prior to|before) sailing", text, re.I)
    if d:
        return int(d.group(1)), None
    mo = re.search(r"(?:at least )?(\d+) months? (?:in advance|prior to sailing|before sailing)", text, re.I)
    if mo:
        return None, int(mo.group(1))
    return None, None


def state_of(offer):
    if not offer:
        return None
    return {"listed": bool(offer.get("listed")), "name": offer.get("name"),
            "credits": offer.get("credits"), "text": offer.get("text")}


def marker_for(old, new, old_since):
    raw = json.dumps([old, new, old_since], sort_keys=True)
    return "offer-" + hashlib.sha256(raw.encode()).hexdigest()[:12]


def eastern_today(now):
    return now.astimezone(fp.MIAMI).date().isoformat()


def from_schema_1(prev):
    """A schema 1 file (5.2.0, "doubleup") as schema 2's multi_credit and last_change. Schema 1
    only ever saw DoubleUp headings, so a listed banner is DoubleUp; its credits are read again
    from its text by the same rule as today's."""
    du = prev.get("doubleup")
    offer = None
    if isinstance(du, dict):
        listed = bool(du.get("listed"))
        name = (read_name(du.get("title")) or "DoubleUp!") if listed else None
        credits = read_credits(du.get("title") or "DoubleUp!", du.get("text"))[0] if listed else None
        offer = {"listed": listed, "title": du.get("title"), "name": name, "credits": credits, "text": du.get("text"),
                 "types": du.get("types"), "min_days": du.get("min_days"), "min_months": du.get("min_months"),
                 "read_on": du.get("read_on"), "since": du.get("since")}
    ch = prev.get("last_change")
    change = None
    if isinstance(ch, dict):
        def side(listed, text):
            if not listed:
                return None, None
            return "DoubleUp!", read_credits("DoubleUp!", text)[0]
        old_name, old_credits = side(ch.get("old_listed"), ch.get("old_text"))
        new_name, new_credits = side(ch.get("new_listed"), ch.get("new_text"))
        change = {"kind": ch.get("kind"), "on": ch.get("on"),
                  "old_listed": ch.get("old_listed"), "old_name": old_name, "old_credits": old_credits, "old_text": ch.get("old_text"),
                  "new_listed": ch.get("new_listed"), "new_name": new_name, "new_credits": new_credits, "new_text": ch.get("new_text"),
                  "marker": ch.get("marker"), "reported": ch.get("reported")}
    return offer, change


def one_time_fix(previous, new):
    """The old state for 5.3.0's one-time fix, or None (see ONE_TIME_FIX)."""
    if not (isinstance(previous, dict) and previous.get("schema_version") == 1 and new and new["listed"]):
        return None
    du, ch = previous.get("doubleup"), previous.get("last_change")
    if not (isinstance(du, dict) and du.get("listed") is False and isinstance(ch, dict)):
        return None
    if (ch.get("kind"), ch.get("on"), ch.get("old_listed"), ch.get("old_text"), ch.get("new_listed")) != \
            ("ended", ONE_TIME_FIX["on"], True, ONE_TIME_FIX["old_text"], False):
        return None
    old = {"listed": True, "name": ONE_TIME_FIX["name"], "credits": ONE_TIME_FIX["credits"], "text": ONE_TIME_FIX["old_text"]}
    return None if old == new else old   # the same DoubleUp back is an ordinary "appeared"


def build(page, previous, now, page_error=None):
    """The new offers file from today's page (or the error reading it) and the previous file."""
    today = eastern_today(now)
    version = previous.get("schema_version") if isinstance(previous, dict) else None
    if version == SCHEMA_VERSION:
        prev_offer, prev_change = previous.get("multi_credit"), previous.get("last_change")
    elif version == 1:
        prev_offer, prev_change = from_schema_1(previous)
    else:
        prev_offer, prev_change = None, None
    out = {
        "schema_version": SCHEMA_VERSION,
        "saved_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "checked_on": today,
        "source": CRUISENEXT_URL,
        "read_ok": False,
        "warnings": [],
        "multi_credit": prev_offer,
        "last_change": prev_change,
    }
    try:
        if page_error:
            raise Unreadable(page_error)
        title, text = read_banner(page)
    except Unreadable as e:
        kept = f"kept the state read on {prev_offer['read_on']}" if prev_offer else "no earlier state to keep"
        out["warnings"].append(f"CruiseNext offer: could not read {CRUISENEXT_URL} ({e}); {kept}")
        return out

    out["read_ok"] = True
    offer = {"listed": text is not None, "title": title, "name": None, "credits": None, "text": text,
             "types": None, "min_days": None, "min_months": None, "read_on": today}
    if text is not None:
        offer["name"] = read_name(title)
        offer["credits"], why = read_credits(title, text)
        if why:
            out["warnings"].append(why)
        offer["types"] = read_types(text)
        offer["min_days"], offer["min_months"] = read_lead_time(text)
        if offer["types"] is None:
            out["warnings"].append(f"CruiseNext offer: could not read which cabin types {offer['name']} covers; one credit is offered")
        if offer["min_days"] is None and offer["min_months"] is None:
            out["warnings"].append(f"CruiseNext offer: could not read how long before sailing to book {offer['name']}; one credit is offered")

    old, new = state_of(prev_offer), state_of(offer)
    old_since = prev_offer.get("since") if prev_offer else None
    fixed = one_time_fix(previous, new)
    if fixed:
        old, old_since = fixed, ONE_TIME_FIX["on"]
        log("One-time fix (5.3.0): the 2026-11-06 'ended' was NCL's change from DoubleUp to another offer")
    if old == new:
        offer["since"] = (prev_offer or {}).get("since") or today
    else:
        offer["since"] = today
        if old is None:
            kind = "started"
        elif old["listed"] and not new["listed"]:
            kind = "ended"
        elif new["listed"] and not old["listed"]:
            kind = "appeared"
        else:
            kind = "changed"
        empty = {"listed": None, "name": None, "credits": None, "text": None}
        o = old or empty
        out["last_change"] = {
            "kind": kind, "on": today,
            "old_listed": o["listed"], "old_name": o["name"], "old_credits": o["credits"], "old_text": o["text"],
            "new_listed": new["listed"], "new_name": new["name"], "new_credits": new["credits"], "new_text": new["text"],
            "marker": marker_for(old, new, old_since),
            "reported": False,
        }
    out["multi_credit"] = offer
    return out


def nice_date(iso):
    d = dt.date.fromisoformat(iso)
    return f"{d.strftime('%b')} {d.day}, {d.year}"


def usable(offer):
    """True when the family page offers more than one credit on this offer."""
    return bool(offer and offer.get("listed") and offer.get("credits") and offer.get("types")
                and (offer.get("min_days") is not None or offer.get("min_months") is not None))


def what_page_does(offer):
    if not offer or not offer.get("listed"):
        return "The family page offers one CruiseNext credit per booking."
    if not usable(offer):
        return ("The family page offers one CruiseNext credit per booking, because the number of credits, the "
                "qualifying cabins or the time before sailing couldn't be read from this text.")
    days, months = offer.get("min_days"), offer.get("min_months")
    lead = f"at least {days} days before sailing" if days is not None else f"at least {months} months before sailing"
    return (f"The family page offers up to {offer['credits']} CruiseNext credits per booking ({short_name(offer['name'])}) on "
            f"{', '.join(TYPE_NAMES[t] for t in offer['types'])} cabins when booked {lead}.")


def credits_text(n):
    return "could not be read (one credit is offered)" if n is None else str(n)


def issue(out):
    """(title, body, marker) for an unreported change, or None."""
    ch = out.get("last_change")
    if not out.get("read_ok") or not ch or ch.get("reported"):
        return None
    offer = out["multi_credit"]
    when = nice_date(ch["on"])
    old_name, new_name = short_name(ch.get("old_name")), short_name(ch.get("new_name"))
    kind = ch["kind"]
    if kind == "started":
        title = f"CruiseNext offer watch started ({when})"
    elif kind == "appeared":
        title = f"CruiseNext offer appeared: {new_name or 'multi-credit offer'} ({when})"
    elif kind == "ended":
        title = f"CruiseNext offer ended: {old_name or 'multi-credit offer'} ({when})"
    elif old_name != new_name:
        title = f"CruiseNext offer changed: {old_name or 'unknown'} to {new_name or 'unknown'} ({when})"
    elif ch.get("old_credits") != ch.get("new_credits"):
        title = (f"CruiseNext offer changed: {new_name}, {ch.get('old_credits') or 'unknown'} to "
                 f"{ch.get('new_credits') or 'unknown'} credits ({when})")
    else:
        title = f"CruiseNext offer text changed: {new_name} ({when})"

    def shown(listed, name, text):
        if listed is None:
            return "(nothing yet: this is the first check)"
        return f'{name}: "{text}"' if listed else "(no multi-credit offer on the page)"

    lines = [
        f"@{REPO_OWNER} NCL's CruiseNext page, checked {when} (Eastern date).",
        "",
        f"Old: {shown(ch['old_listed'], ch.get('old_name'), ch['old_text'])}",
    ]
    if ch["old_listed"]:
        lines.append(f"Old credits: {credits_text(ch.get('old_credits'))}")
    lines.append(f"New: {shown(ch['new_listed'], ch.get('new_name'), ch['new_text'])}")
    if ch["new_listed"]:
        lines.append(f"New credits: {credits_text(ch.get('new_credits'))}")
    lines.append("")
    if offer.get("listed"):
        types = offer.get("types")
        lines.append("Qualifying cabins read from the text: " + (", ".join(TYPE_NAMES[t] for t in types) if types else "could not be read"))
        if offer.get("min_days") is not None:
            lines.append(f"Time before sailing: at least {offer['min_days']} days")
        elif offer.get("min_months") is not None:
            lines.append(f"Time before sailing: at least {offer['min_months']} months")
        else:
            lines.append("Time before sailing: could not be read")
    for w in out.get("warnings") or []:
        lines.append(f"Warning: {w}")
    lines += [what_page_does(offer), "", f"Link: {CRUISENEXT_URL}", "",
              "One issue is opened per change, never one per day.", f"State id: {ch['marker']}"]
    return title, "\n".join(lines) + "\n", ch["marker"]


def write_json(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.write("\n")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    ap.add_argument("--previous", help="the current data/offers.json (schema 1 or 2)")
    ap.add_argument("--issue-dir", help="where to write title.txt, body.md and marker.txt for an unreported change")
    ap.add_argument("--mark-reported", metavar="PATH", help="mark the last change in PATH as reported (its issue is open)")
    args = ap.parse_args(argv)

    if args.mark_reported:
        with open(args.mark_reported, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("last_change"):
            data["last_change"]["reported"] = True
        write_json(args.mark_reported, data)
        log(f"Marked the last CruiseNext offer change as reported in {args.mark_reported}")
        return 0
    if not args.out:
        ap.error("--out is required")

    previous = None
    if args.previous and os.path.exists(args.previous):
        try:
            with open(args.previous, encoding="utf-8") as f:
                previous = json.load(f)
        except Exception as e:
            log(f"Could not read the previous offers file ({e}); starting fresh")

    page, error = None, None
    try:
        page = fp.request(CRUISENEXT_URL, page=True)
    except Exception as e:   # one page load, tried once; the previous state is kept
        error = f"{type(e).__name__}: {e}"
    out = build(page, previous, dt.datetime.now(dt.timezone.utc), page_error=error)
    write_json(args.out, out)
    log(f"Wrote {args.out}")

    offer = out["multi_credit"]
    if offer and offer.get("listed"):
        print(f"::notice title=CruiseNext offer::{offer['name']} ({credits_text(offer['credits'])} credits) "
              f"on NCL's CruiseNext page: {offer['text']}")
    elif offer:
        print("::notice title=CruiseNext offer::no multi-credit offer (DoubleUp, TripleUp, QuadUp) on NCL's CruiseNext page")
    for w in out["warnings"]:
        print(f"::warning title=CruiseNext offer watch::{w}")

    found = issue(out)
    if found and args.issue_dir:
        os.makedirs(args.issue_dir, exist_ok=True)
        for name, text in zip(("title.txt", "body.md", "marker.txt"), found):
            with open(os.path.join(args.issue_dir, name), "w", encoding="utf-8") as f:
                f.write(text)
        log(f"CruiseNext offer change to report: {found[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
