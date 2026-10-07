# Changelog

All notable changes to this project are listed here. Versions follow Semantic Versioning (MAJOR.MINOR.PATCH). The version in `index.html` (`APP_VERSION`) must match the newest entry below; `tools/check_release.py` enforces this.

## [3.0.0] - 2026-10-07

The page is now a decision guide for the family's June 2027 cruise. It replaces the Norwegian Joy (Nov 2026) cabin selector, which stays available on `main` until this branch is merged and in git history after that.

### Added
- Three options side by side: 3 nights on the Norwegian Getaway (Jun 11 to Jun 14, 2027), 5 nights on the Norwegian Aura (Jun 14 to Jun 19, 2027), and 8 nights on both back to back.
- Guest selector for 2, 3, 4 or 5 people per cabin, and a cabin type selector (Inside, Oceanview, Balcony, Club Balcony Suite, Suite, The Haven). Studio is hidden because it only fits one guest.
- 8-night toggle: "Same cabin on both ships" (like for like matching, with the mini-suite rule) or "Different cabin on each ship" (a picker for each ship).
- Per person and total prices, cost per night, tax notes ("Includes about $200 / $210 / $410 per guest in taxes"), the "Estimated add-on (NCL's cheapest cabin for that party size)" line for 3 to 5 guests, and a "Free at Sea charge: not yet available" placeholder.
- Plain language box explaining the ship change in Miami on Jun 14, the expected terminal, and the two visits to Great Stirrup Cay.
- Table of every cabin type for the chosen party size.
- "Prices as of" date from the data file, and the CruiseFeed cross check status in the footer.
- `data/prices.json`, written by `tools/fetch_prices.py` from NCL's public sailing pages (8 page loads: both sailings at 2, 3, 4 and 5 guests).
- `tools/check_prices.py`: format check for the data file.
- `tools/check_release.py` and `.github/workflows/check.yml`: release gate on every push and pull request (data format, version matches this changelog).
- `.github/workflows/refresh-prices.yml`: daily refresh on GitHub's runners, a weekly CruiseFeed cross check when the `CRUISEFEED_KEY` repo secret exists, and a format check that keeps the old data file when the new one is bad.

### Removed
- The Norwegian Joy cabin cards, deposit options, package toggles and child age inputs. The old CSV price files are no longer read by the page.

## [2.5.0] and earlier

Norwegian Joy (Nov 20 to Nov 23, 2026) cabin selector. See the git history on `main` for details.
