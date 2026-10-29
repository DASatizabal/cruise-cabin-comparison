#!/usr/bin/env python3
"""DoubleUp watch (5.2.0): reads NCL's CruiseNext page once a day and saves the DoubleUp banner.

  python3 tools/fetch_offers.py --previous data/offers.json --out data/offers.new.json --issue-dir DIR
  python3 tools/fetch_offers.py --mark-reported data/offers.new.json

1 NCL page load per run (GET https://www.ncl.com/cruise-deals/cruisenext, through
fetch_prices.request(): the address guard applies, tried once, no cookies). Runs in the
"refresh" job of .github/workflows/refresh-prices.yml, before the prices.

What is saved (data/offers.json, schema 1, checked by tools/check_offers.py): whether the
"Limited-Time Offer: DoubleUp!" banner is on the page, its exact text, the cabin types and the
time before sailing read from that text, and the last change (old and new state, the Eastern
date, and whether its GitHub issue has been opened). Wording that can't be read is saved as
null with a warning; the page then never offers two credits (never guessed).

A page that can't be read (an error, or a page without NCL's CruiseNext terms) keeps the
previous state with read_ok false and a warning. It never fails the price run and never opens
an issue: only a page that was read decides that the banner appeared, changed or ended.

Issues: when the state differs from the previous file's (or there is no previous state: the
"DoubleUp watch started" issue), --issue-dir gets title.txt, body.md and marker.txt. The
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

SCHEMA_VERSION = 1
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
DOUBLEUP = re.compile(r"double\s*-?\s*up", re.I)
FOOTNOTE = re.compile(r"\s*<(?:sub|sup|small)\b", re.I)
NEAR = 4000   # characters after the heading in which the offer paragraph must start


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
    """(title, text) of the DoubleUp banner, or (None, None) when the page has none.

    Raises Unreadable when the page doesn't look like NCL's CruiseNext page (it must carry the
    CruiseNext credit terms) or a DoubleUp heading has no text after it.
    """
    whole = plain(page)
    if "CruiseNext" not in whole or not re.search(r"per stateroom", whole, re.I):
        raise Unreadable("the page has no CruiseNext credit terms (moved, blocked or changed)")
    for m in HEADING.finditer(page):
        title = plain(m.group(2))
        if not DOUBLEUP.search(title):
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
    return None, None


def read_types(text):
    """Cabin types the DoubleUp text names, or None when the wording isn't understood."""
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


def state_of(doubleup):
    if not doubleup:
        return None
    return {"listed": bool(doubleup.get("listed")), "text": doubleup.get("text")}


def marker_for(old, new, old_since):
    raw = json.dumps([old, new, old_since], sort_keys=True)
    return "doubleup-" + hashlib.sha256(raw.encode()).hexdigest()[:12]


def eastern_today(now):
    return now.astimezone(fp.MIAMI).date().isoformat()


def build(page, previous, now, page_error=None):
    """The new offers file from today's page (or the error reading it) and the previous file."""
    today = eastern_today(now)
    prev = previous if isinstance(previous, dict) and previous.get("schema_version") == SCHEMA_VERSION else None
    prev_du = (prev or {}).get("doubleup")
    out = {
        "schema_version": SCHEMA_VERSION,
        "saved_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "checked_on": today,
        "source": CRUISENEXT_URL,
        "read_ok": False,
        "warnings": [],
        "doubleup": prev_du,
        "last_change": (prev or {}).get("last_change"),
    }
    try:
        if page_error:
            raise Unreadable(page_error)
        title, text = read_banner(page)
    except Unreadable as e:
        kept = f"kept the state read on {prev_du['read_on']}" if prev_du else "no earlier state to keep"
        out["warnings"].append(f"DoubleUp: could not read {CRUISENEXT_URL} ({e}); {kept}")
        return out

    out["read_ok"] = True
    du = {"listed": text is not None, "title": title, "text": text, "types": None,
          "min_days": None, "min_months": None, "read_on": today}
    if text is not None:
        du["types"] = read_types(text)
        du["min_days"], du["min_months"] = read_lead_time(text)
        if du["types"] is None:
            out["warnings"].append("DoubleUp: could not read which cabin types qualify; two credits are not offered")
        if du["min_days"] is None and du["min_months"] is None:
            out["warnings"].append("DoubleUp: could not read how long before sailing to book; two credits are not offered")

    old, new = state_of(prev_du), state_of(du)
    if old == new:
        du["since"] = prev_du.get("since") or today
    else:
        du["since"] = today
        if old is None:
            kind = "started"
        elif old["listed"] and not new["listed"]:
            kind = "ended"
        elif new["listed"] and not old["listed"]:
            kind = "appeared"
        else:
            kind = "changed"
        out["last_change"] = {
            "kind": kind, "on": today,
            "old_listed": old["listed"] if old else None, "old_text": old["text"] if old else None,
            "new_listed": new["listed"], "new_text": new["text"],
            "marker": marker_for(old, new, prev_du.get("since") if prev_du else None),
            "reported": False,
        }
    out["doubleup"] = du
    return out


def nice_date(iso):
    d = dt.date.fromisoformat(iso)
    return f"{d.strftime('%b')} {d.day}, {d.year}"


def what_page_does(du):
    if not du or not du.get("listed"):
        return "The family page offers one CruiseNext credit per booking."
    types, days, months = du.get("types"), du.get("min_days"), du.get("min_months")
    if types is None or (days is None and months is None):
        return ("The family page offers one CruiseNext credit per booking, because the qualifying cabins "
                "or the time before sailing couldn't be read from this text.")
    lead = f"at least {days} days before sailing" if days is not None else f"at least {months} months before sailing"
    return (f"The family page offers two CruiseNext credits on {', '.join(TYPE_NAMES[t] for t in types)} cabins "
            f"when booked {lead}.")


def issue(out):
    """(title, body, marker) for an unreported change, or None."""
    ch = out.get("last_change")
    if not out.get("read_ok") or not ch or ch.get("reported"):
        return None
    du = out["doubleup"]
    when = nice_date(ch["on"])
    title = {"started": f"DoubleUp watch started ({when})",
             "appeared": f"DoubleUp offer appeared ({when})",
             "ended": f"DoubleUp offer ended ({when})",
             "changed": f"DoubleUp offer text changed ({when})"}[ch["kind"]]

    def shown(listed, text):
        if listed is None:
            return "(nothing yet: this is the first check)"
        return f'"{text}"' if listed else "(no DoubleUp banner on the page)"

    lines = [
        f"@{REPO_OWNER} NCL's CruiseNext page, checked {when} (Eastern date).",
        "",
        f"Old text: {shown(ch['old_listed'], ch['old_text'])}",
        f"New text: {shown(ch['new_listed'], ch['new_text'])}",
        "",
    ]
    if du.get("listed"):
        types = du.get("types")
        lines.append("Qualifying cabins read from the text: " + (", ".join(TYPE_NAMES[t] for t in types) if types else "could not be read"))
        if du.get("min_days") is not None:
            lines.append(f"Time before sailing: at least {du['min_days']} days")
        elif du.get("min_months") is not None:
            lines.append(f"Time before sailing: at least {du['min_months']} months")
        else:
            lines.append("Time before sailing: could not be read")
    lines += [what_page_does(du), "", f"Link: {CRUISENEXT_URL}", "",
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
    ap.add_argument("--previous", help="the current data/offers.json")
    ap.add_argument("--issue-dir", help="where to write title.txt, body.md and marker.txt for an unreported change")
    ap.add_argument("--mark-reported", metavar="PATH", help="mark the last change in PATH as reported (its issue is open)")
    args = ap.parse_args(argv)

    if args.mark_reported:
        with open(args.mark_reported, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("last_change"):
            data["last_change"]["reported"] = True
        write_json(args.mark_reported, data)
        log(f"Marked the last DoubleUp change as reported in {args.mark_reported}")
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

    du = out["doubleup"]
    if du and du.get("listed"):
        print(f"::notice title=DoubleUp::on NCL's CruiseNext page: {du['text']}")
    elif du:
        print("::notice title=DoubleUp::no DoubleUp banner on NCL's CruiseNext page")
    for w in out["warnings"]:
        print(f"::warning title=DoubleUp watch::{w}")

    found = issue(out)
    if found and args.issue_dir:
        os.makedirs(args.issue_dir, exist_ok=True)
        for name, text in zip(("title.txt", "body.md", "marker.txt"), found):
            with open(os.path.join(args.issue_dir, name), "w", encoding="utf-8") as f:
                f.write(text)
        log(f"DoubleUp change to report: {found[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
