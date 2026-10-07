#!/usr/bin/env python3
"""Release gate. Runs on every push and pull request (.github/workflows/check.yml).

  python3 tools/check_release.py

Fails when:
  - data/prices.json does not pass the format check (tools/check_prices.py)
  - the version in index.html (APP_VERSION) is not Semantic Versioning, or
    does not match the newest entry in CHANGELOG.md
  - index.html no longer reads data/prices.json
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import check_prices  # noqa: E402

SEMVER = r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def main():
    problems = []

    import json
    try:
        data = json.loads(read("data/prices.json"))
        problems += ["data/prices.json: " + e for e in check_prices.check(data)]
    except Exception as e:
        problems.append(f"data/prices.json cannot be read: {e}")

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

    if problems:
        print("Release check FAILED:")
        for p in problems:
            print("  - " + p)
        return 1
    print(f"Release check OK (version {page_version})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
