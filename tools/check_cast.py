#!/usr/bin/env python3
"""Format check for the splash page's cast list and its files (splash/, 5.3.0).

  python3 tools/check_cast.py [splash folder]

The splash page (splash/index.html) is a stage: a still deck picture with one actor per person on
top. splash/cast.json (schema 1) lists the cast:

  schema_version  1
  deck            the deck picture in splash/ (deck.svg, or deck.webp for your own art), 3:5 portrait
  cast[]          id         a short lowercase id (letters, digits and single dashes), stored by the
                             cruise-family-alerts Worker for who is aboard; never change it
                  name       first name only, shown under the actor ("Zin", "Kid 1", "David Jr.",
                             "Daniel's guest"); never a last name
                  actor      actors/<id>.webp: a WebP with transparency (animated or still), 3:4
                             (180 x 240 suggested), at most 150 KB
                  lounger    {"x", "y"}: the lounger's center in % of the deck picture
                  still      optional, actors/<id>-still.webp: the same person standing still, shown
                             when the phone asks for less motion (same rules as actor)

Also checks every file in splash/: only the page, the cast list, the deck, the two opening
pictures (hero-family.webp, hero-ship.webp, at most 400 KB each) and the actors listed above plus
actors/placeholder.webp (the fallback when an actor can't be loaded). Run by
tools/check_release.py; "Deploy site" publishes splash/ only after the release check passes.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPLASH = os.path.join(ROOT, "splash")

MAX_CAST = 21               # the dock has 21 spots (3 rows of 7)
ACTOR_MAX_BYTES = 150_000
HERO_MAX_BYTES = 400_000
DECK_MAX_BYTES = 300_000
ID_RE = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
# First names only: one word, optionally "Jr." or "Sr." or a number after it, or a placeholder
# like "Daniel's guest". Two words at most, so a last name can't slip in.
NAME_RE = re.compile(r"[A-Z][A-Za-z'\-]{0,19}( (Jr\.|Sr\.|[0-9]{1,2}|guest))?")
ACTOR_RE = re.compile(r"actors/[a-z0-9]+(-[a-z0-9]+)*\.webp")
DECK_NAMES = {"deck.svg", "deck.webp"}
FIXED = {"index.html", "cast.json", "hero-family.webp", "hero-ship.webp", "actors/placeholder.webp"}
LOUNGER_X = (3, 97)
LOUNGER_Y = (8, 60)         # the deck part of the picture (the dock is below)
MIN_APART = 8               # percent points between two loungers


def webp_info(data):
    """(width, height, has_alpha, animated) of a WebP file, or None if it isn't one."""
    if len(data) < 30 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    kind, body = data[12:16], data[20:]
    if kind == b"VP8X" and len(body) >= 10:
        flags = body[0]
        w = 1 + int.from_bytes(body[4:7], "little")
        h = 1 + int.from_bytes(body[7:10], "little")
        return w, h, bool(flags & 0x10), bool(flags & 0x02)
    if kind == b"VP8L" and len(body) >= 5 and body[0] == 0x2F:
        bits = int.from_bytes(body[1:5], "little")
        return 1 + (bits & 0x3FFF), 1 + ((bits >> 14) & 0x3FFF), bool((bits >> 28) & 1), False
    if kind == b"VP8 " and len(body) >= 10:
        return int.from_bytes(body[6:8], "little") & 0x3FFF, int.from_bytes(body[8:10], "little") & 0x3FFF, False, False
    return None


def actor_problems(folder, path, label):
    full = os.path.join(folder, path)
    if not os.path.isfile(full):
        return [f"{label}: {path} is missing"]
    with open(full, "rb") as f:
        data = f.read()
    errors = []
    if len(data) > ACTOR_MAX_BYTES:
        errors.append(f"{label}: {path} is {len(data):,} bytes (at most {ACTOR_MAX_BYTES:,})")
    info = webp_info(data)
    if not info:
        return errors + [f"{label}: {path} is not a WebP file"]
    w, h, alpha, _ = info
    if not alpha:
        errors.append(f"{label}: {path} has no transparency (export it as WebP with an alpha channel)")
    if w > 600 or h > 800 or h < 64:
        errors.append(f"{label}: {path} is {w} x {h} (180 x 240 suggested, at most 600 x 800)")
    elif abs(w / h - 0.75) > 0.03:
        errors.append(f"{label}: {path} is {w} x {h}, not 3:4 (180 x 240 suggested)")
    return errors


def check(cast, folder=SPLASH):
    errors = []
    err = errors.append
    if not isinstance(cast, dict):
        return ["cast.json is not a JSON object"]
    extra = set(cast) - {"schema_version", "deck", "cast"}
    if extra:
        err(f"unexpected keys {sorted(extra)}")
    if cast.get("schema_version") != 1:
        err("schema_version must be 1")
    deck = cast.get("deck")
    if deck not in DECK_NAMES:
        err('deck must be "deck.svg" or "deck.webp"')
    elif not os.path.isfile(os.path.join(folder, deck)):
        err(f"deck: {deck} is missing")
    elif os.path.getsize(os.path.join(folder, deck)) > DECK_MAX_BYTES:
        err(f"deck: {deck} is more than {DECK_MAX_BYTES:,} bytes")
    people = cast.get("cast")
    if not isinstance(people, list) or not 1 <= len(people) <= MAX_CAST:
        return errors + [f"cast must be a list of 1 to {MAX_CAST} people"]
    ids, names, spots, files = set(), set(), [], set()
    for i, p in enumerate(people):
        label = f"cast[{i}]"
        if not isinstance(p, dict):
            err(f"{label} is not an object")
            continue
        extra = set(p) - {"id", "name", "actor", "lounger", "still"}
        if extra:
            err(f"{label}: unexpected keys {sorted(extra)}")
        pid = p.get("id")
        if not isinstance(pid, str) or len(pid) > 30 or not ID_RE.fullmatch(pid):
            err(f"{label}: id must be lowercase letters, digits and single dashes, at most 30 characters")
        elif pid in ids:
            err(f"{label}: id {pid} is used twice")
        else:
            ids.add(pid)
            label = f"cast {pid}"
        name = p.get("name")
        if not isinstance(name, str) or not NAME_RE.fullmatch(name):
            err(f"{label}: name must be a first name only (like Zin, Kid 1, David Jr. or Daniel's guest)")
        elif name.lower() in names:
            err(f"{label}: the name {name} is used twice (first names must be unique, so a Make Selection guest matches one person)")
        else:
            names.add(name.lower())
        for key in ("actor", "still"):
            if key == "still" and key not in p:
                continue
            path = p.get(key)
            if not isinstance(path, str) or not ACTOR_RE.fullmatch(path):
                err(f"{label}: {key} must be actors/<name>.webp")
                continue
            if key == "actor" and isinstance(pid, str) and path != f"actors/{pid}.webp":
                err(f"{label}: actor must be actors/{pid}.webp (one file per person, named by the id)")
            files.add(path)
            errors += actor_problems(folder, path, label)
        spot = p.get("lounger")
        if (not isinstance(spot, dict) or set(spot) != {"x", "y"} or
                not all(isinstance(spot[k], (int, float)) and not isinstance(spot[k], bool) for k in ("x", "y"))):
            err(f"{label}: lounger must be {{\"x\": number, \"y\": number}}")
            continue
        x, y = spot["x"], spot["y"]
        if not (LOUNGER_X[0] <= x <= LOUNGER_X[1] and LOUNGER_Y[0] <= y <= LOUNGER_Y[1]):
            err(f"{label}: lounger x must be {LOUNGER_X[0]} to {LOUNGER_X[1]} and y {LOUNGER_Y[0]} to {LOUNGER_Y[1]} (the deck)")
        for other, (ox, oy) in spots:
            if abs(x - ox) < MIN_APART and abs(y - oy) < MIN_APART:
                err(f"{label}: lounger is on top of {other}'s")
        spots.append((label, (x, y)))

    # Only the expected files are published.
    allowed = FIXED | files | ({deck} if isinstance(deck, str) else set())
    for base, _, names_ in os.walk(folder):
        for n in names_:
            rel = os.path.relpath(os.path.join(base, n), folder).replace(os.sep, "/")
            if rel not in allowed:
                err(f"{rel}: not used by the splash page (remove it, or list it in cast.json)")
    for rel in sorted(FIXED):
        full = os.path.join(folder, rel)
        if not os.path.isfile(full):
            err(f"{rel} is missing")
        elif rel.startswith("hero-"):
            with open(full, "rb") as f:
                data = f.read()
            if not webp_info(data):
                err(f"{rel} is not a WebP file")
            if len(data) > HERO_MAX_BYTES:
                err(f"{rel} is {len(data):,} bytes (at most {HERO_MAX_BYTES:,}; 1600 px wide at quality 75 is plenty)")
        elif rel == "actors/placeholder.webp":
            errors += actor_problems(folder, rel, "placeholder")
    return errors


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else SPLASH
    try:
        with open(os.path.join(folder, "cast.json"), encoding="utf-8") as f:
            cast = json.load(f)
    except Exception as e:
        print(f"cast.json cannot be read: {e}")
        return 1
    errors = check(cast, folder)
    for e in errors:
        print("  - " + e)
    print("cast.json OK" if not errors else f"cast.json: {len(errors)} problems")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
