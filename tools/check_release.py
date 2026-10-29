#!/usr/bin/env python3
"""Release gate. Runs on every push and pull request (.github/workflows/check.yml).

  python3 tools/check_release.py

Fails when:
  - data/prices.json does not pass the format check (tools/check_prices.py)
  - data/florida.json, when present, does not pass its format check (tools/check_florida.py)
  - data/offers.json, when present, does not pass its format check (tools/check_offers.py)
  - the version in index.html (APP_VERSION) is not Semantic Versioning, or
    does not match the newest entry in CHANGELOG.md
  - index.html no longer reads data/prices.json
  - the family alerts Worker (tools/family-alerts/worker.js) still accepts requests from the
    raw.githack.com preview (TEST_ORIGIN is not ""): temporary for testing, never merged
  - index.html sets only one of FAMILY_API and TURNSTILE_SITE_KEY, or a FAMILY_API that isn't https
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import check_florida  # noqa: E402
import check_offers  # noqa: E402
import check_prices  # noqa: E402

SEMVER = r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def family_checks(worker, page):
    """The family alerts Worker (5.2.0): the preview's test address is switched off before merging,
    and the page has both or neither of the Worker's address and the Turnstile key."""
    problems = []
    m = re.search(r'^const TEST_ORIGIN = "([^"]*)";$', worker, re.M)
    if not m:
        problems.append('tools/family-alerts/worker.js: the line const TEST_ORIGIN = "..."; is missing')
    elif m.group(1):
        problems.append(f'tools/family-alerts/worker.js: TEST_ORIGIN is "{m.group(1)}" (testing from the preview). '
                        'Set it to "" and paste the file into the Worker again before merging.')
    api = re.search(r'const FAMILY_API = "([^"]*)";', page)
    key = re.search(r'const TURNSTILE_SITE_KEY = "([^"]*)";', page)
    if not api or not key:
        problems.append("index.html: FAMILY_API or TURNSTILE_SITE_KEY not found")
    elif bool(api.group(1)) != bool(key.group(1)):
        problems.append("index.html: FAMILY_API and TURNSTILE_SITE_KEY must both be set or both be empty")
    elif api.group(1) and not re.fullmatch(r"https://[a-z0-9.-]+(/[A-Za-z0-9._-]+)*", api.group(1)):
        problems.append(f"index.html: FAMILY_API {api.group(1)} is not an https address without a trailing slash")
    return problems


def main():
    problems = []

    import json
    try:
        data = json.loads(read("data/prices.json"))
        problems += ["data/prices.json: " + e for e in check_prices.check(data, allow_schema_3=True)]
    except Exception as e:
        problems.append(f"data/prices.json cannot be read: {e}")

    # Written by the owner's AI PC (tools/fetch_florida.py); optional, the page shows website
    # prices without it.
    if os.path.exists(os.path.join(ROOT, "data", "florida.json")):
        try:
            florida = json.loads(read("data/florida.json"))
            problems += ["data/florida.json: " + e for e in check_florida.check(florida)]
        except Exception as e:
            problems.append(f"data/florida.json cannot be read: {e}")

    # Written daily by the price job (tools/fetch_offers.py); optional, the page offers one
    # CruiseNext credit without it.
    if os.path.exists(os.path.join(ROOT, "data", "offers.json")):
        try:
            offers = json.loads(read("data/offers.json"))
            problems += ["data/offers.json: " + e for e in check_offers.check(offers)]
        except Exception as e:
            problems.append(f"data/offers.json cannot be read: {e}")

    page = read("index.html")
    m = re.search(r'const APP_VERSION = "([^"]+)"', page)
    if not m:
        problems.append('index.html: const APP_VERSION = "x.y.z" not found')
        page_version = None
    else:
        page_version = m.group(1)
        if not re.fullmatch(SEMVER, page_version):
            problems.append(f"index.html: APP_VERSION {page_version} is not x.y.z")

    m = re.search(r"^## \[(" + SEMVER + r")\]", read("CHANGELOG.md"), re.M)
    if not m:
        problems.append("CHANGELOG.md: no '## [x.y.z]' entry found")
    elif page_version and m.group(1) != page_version:
        problems.append(f"CHANGELOG.md newest entry is {m.group(1)} but index.html says {page_version}")

    if "data/prices.json" not in page:
        problems.append("index.html does not read data/prices.json")

    problems += family_checks(read("tools/family-alerts/worker.js"), page)

    if problems:
        print("Release check FAILED:")
        for p in problems:
            print("  - " + p)
        return 1
    print(f"Release check OK (version {page_version})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
