# Changelog

All notable changes to this project are listed here. Versions follow Semantic Versioning (MAJOR.MINOR.PATCH). The version in `index.html` (`APP_VERSION`) must match the newest entry below; `tools/check_release.py` enforces this.

## [4.6.0] - 2026-10-09

Free at Sea choices per cabin, crew gratuities, and what is due before sailing versus onboard.

### Added
- Free at Sea switches for each cabin, in the same iOS style as the 2.x page: Unlimited Open Bar (on), Specialty Dining (on) and Free at Sea Plus (off). All guests in a cabin share the choice. For 8 nights the Getaway and the Aura each have their own set, since they are separate bookings. Turning Free at Sea Plus on also turns on Open Bar and Specialty Dining; turning either of those off turns Plus off.
- Free at Sea Plus per guest per night: 21 and over at the adult rate, a guest 1 or 2 aged 3 to 20 at the child rate; 2 and under, and under 21 in position 3 or later, are not charged.
- Service charges (crew gratuities) per guest per night for every guest 3 and older, at NCL's Suite and Haven rate or standard rate, as their own line. Guests covered by Free at Sea Plus don't pay them (Plus includes prepaid service charges).
- A "Gratuities total" line (service charges, Open Bar and Specialty Dining gratuities) in every total.
- A "Gratuities" card with a "Prepay gratuities" / "Pay onboard on the last day" switch and the note "Daily gratuities can be adjusted or removed onboard at Guest Services." Every total is split into "Due before you sail" and "Charged onboard".
- `rates` in `data/prices.json`, read daily from NCL's pages with source and date: Free at Sea Plus adult and child rates and the Open Bar and soda rates (promotion terms page), and the service charge rates and minimum age (NCL's service charge FAQ). If a page can't be read, the previous rate is kept with a warning. The Open Bar and soda amounts from NCL's price summary are cross checked against these rates.
- The price fetch retries an availability answer that shows nothing available at a real price, and a price summary with a $0 total, after 30, 60 and 120 seconds.

### Changed
- Light count days re-check only counts under 15 (was under 50), plus the next pricier category each one needs. About 75 calls instead of about 95 (full sweep about 140).

## [4.5.0] - 2026-10-09

Cabin counts are separated from prices, so prices never depend on them, and count traffic is lighter.

### Added
- `data/counts.json`, a separate cabin counts file with its own `saved_at`, written by the new `tools/fetch_counts.py` and checked by the new `tools/check_counts.py`.
- Count schedule: a full sweep (every category, every party size) when the last full sweep was 3 or more days ago, and on the other days a light re-check of only the counts that were under 50, plus the next pricier category each one needs for the subtraction. 3 seconds between count calls. The mode is recorded in the file (`mode`, `mode_reason`, `last_full_sweep`) and in the commit message ("Refresh cabin counts DATE (full)" or "(light)").
- "Refresh prices" can be run by hand with a cabin counts choice: auto, full or light.
- The page shows "Cabins left as of [date]" from `counts.json`. If the file is missing, unreadable or more than 7 days old, the date and every count label are hidden.

### Changed
- "Refresh prices" now has two parts. The price job (itineraries, availability, price summaries, age test) commits `data/prices.json` and publishes on its own, as before. A separate counts job runs after it (even if the price job failed), commits `data/counts.json` and publishes again. If the counts job fails, the published prices stay and the page keeps the last good counts.
- Descriptions are built on the page from the price file plus, when fresh, where each category's open cabins are from the counts file. `data/prices.json` no longer holds counts or open-cabin details.
- "Deploy site" copies `data/counts.json` when present, takes a label for its artifact name (`prices` or `counts`), and queues publishes in the deploy job's concurrency group.
- The price job's time limit is back to 20 minutes; the counts job has 60.

## [4.4.0] - 2026-10-08

### Added
- Cabins left: each category button, each dropdown option in Different cabins mode and each row of the full tables shows "Plenty left" (50 or more), "Getting low" (10 to 49) or "Only X left" (under 10). Nothing is shown for Guarantee cabins or counts marked unreliable.
- The fetch script reads NCL's cabin/availability call for every available non-Guarantee category at every party size, most expensive first, and counts cabins by subtracting location totals. Counts are marked unreliable (and not shown) when a call returns another cabin type's code, when two categories tie in price, or when the subtraction is not positive. The reasons are logged in the data file under `checks.counts`.
- Descriptions gain where each category's open cabins are: missing decks (the Aura's grouped Inside and Balcony codes) and missing forward, midship, aft locations (the Getaway's grouped codes), taken only from NCL's list of open cabins.
- The run stops if a cabin/availability answer mentions "hold" or "heldUntil".

### Changed
- Every cabin picker defaults to the cheapest available non-Guarantee category. Guarantee categories stay in the lists and can still be picked; when a type has only Guarantee categories available, the cheapest Guarantee one is the default.
- Workflow actions moved to their Node.js 24 versions: actions/checkout v7, actions/configure-pages v6, actions/upload-pages-artifact v5 (uses upload-artifact v7), actions/deploy-pages v5. Every job runs on `ubuntu-24.04` instead of `ubuntu-latest`.
- The refresh job may now take up to 45 minutes (about 160 NCL calls).

### Fixed
- POST requests to NCL no longer follow redirects. A redirect, a 5xx or a network error is logged with its status code and Location header and retried after 30, 60 and 120 seconds before the run fails.
- "Deploy site" uploads in a "build" job and publishes in a separate "deploy" job, names the artifact per run attempt, and retries the publish once after 30 seconds. This addresses deploy-pages reporting 0 artifacts right after a successful upload in the same job.

## [4.3.0] - 2026-10-08

The site is now published by GitHub Actions, so the daily price refresh reaches the family page.

### Added
- `.github/workflows/deploy-pages.yml` ("Deploy site"): publishes `index.html` and `data/prices.json` to GitHub Pages on every push to `main`, on demand, and when called by the refresh. It runs the release check first and only ever publishes `main`.
- The daily refresh now publishes the site in the same run, right after its data commit ("publish" job). Commits made with `GITHUB_TOKEN` don't start a Pages build on their own, which is why this is needed.
- Keep-alive for the daily schedule ("keepalive" job): on every scheduled run on `main`, the refresh marks its own workflow enabled again through GitHub's API. GitHub turns off scheduled workflows in public repos after 60 days without repository activity and doesn't define activity, so this is a safety net on top of the daily data commit. It never fails the run.

### Changed
- GitHub Pages must be switched from "Deploy from a branch" to "GitHub Actions" (Settings, Pages, Source). See NOTES.md, "Publishing (4.3.0)", for the order of steps.

## [4.2.1] - 2026-10-07

### Fixed
- When a cabin list has only one available option, it now shows that option as a button that is already selected, with no tap action and no hover effect. Before, the 3 and 5 night cards showed no list at all in that case. This applies to every cabin picker, including both ship pickers in Different cabins mode (which show the single option as a selected button instead of a one-item dropdown).

## [4.2.0] - 2026-10-07

Kid pricing now follows NCL's confirmed age rules.

### Added
- Guests are listed in NCL's order: adults first, then kids oldest first.
- Unlimited Open Bar per guest: 21 and over pay the full gratuity, a guest under 21 in position 2 (only possible with 1 adult) pays NCL's soda package instead, and guests under 21 in position 3 or later pay nothing. Specialty Dining: 13 and over pay, under 13 eat free, in any position.
- Breakdown wording such as "Unlimited Open Bar: 1 guest x $96, 1 guest x $37.50 (soda package, under 21)" and "Specialty Dining: 2 guests x $20 (under 13 eat free)". Amounts with cents show the cents.
- Kid dropdowns are labeled "Kid 1 age on Jun 11, 2027", with the note "Use each kid's age on Jun 11, 2027." under the Kids counter. The guest summary shows NCL's guest order.
- Daily age test in the fetch script: one price summary per ship for 1 adult, a 15 year old and a 7 year old (birth dates only, no names). The adult Open Bar, soda package and Specialty Dining amounts per guest are read from it, so the Aura's numbers come from NCL ($160, $62.50 and $40).
- Age cross check: the page's formula for that party must match NCL's total within $5 on each ship, or the run fails. The run also fails if NCL's age rules change.

### Fixed
- Cabin totals now use NCL's average per person price with cents (for example $455.66), so a 3 guest total matches NCL to the dollar. Before, rounding the average first could add $1.

## [4.1.0] - 2026-10-07

### Added
- Plain cabin descriptions instead of technical names, for example "Balcony, Decks 12 to 14 (BA)" or "Family Balcony, Decks 13 and 14, midship (B4)". The NCL code stays in small grey text. Sizes are shown where NCL gives them for that one code.
- Description fields in the data file (`description`, `decks`, `location`, `size`, `details_source`, `shares_ncl_description_with`), rebuilt on every daily refresh. The format check covers them.

### Changed
- "Kids (under 21)" sits directly under "Adults (21+)", and the kid age dropdowns appear right under the Kids counter.
- Cabin type has its own card, directly below "Who is in the cabin".
- The cabin selection lists (the tap-to-choose category buttons, and for 8 nights the Same/Different toggle and the two cabin pickers) now sit between each option card's heading and its prices.

## [4.0.0] - 2026-10-07

Prices now come from NCL's booking system, cabin by cabin, with every line of the total shown. The data file format changed (schema 2), so this is a major version.

### Added
- Specific cabin categories (for example Family Balcony B4) under each cabin type, with prices for the current party, cheapest first. Tap one to choose it.
- Guest counters for "Adults (21+)" and "Kids (under 21)", with an age dropdown for each kid. Adults plus kids must total 2 to 5 with at least 1 adult; anything else is blocked with a plain message.
- Each total shows its own lines: cruise fare, NCL's taxes, fees and port expenses, Unlimited Open Bar and Specialty Dining gratuities, then the total, per person price and cost per night.
- Free at Sea gratuities by age: 21 and over pay Open Bar and Specialty Dining, 13 to 20 pay Specialty Dining only, 12 and under pay neither. The page shows who is charged, for example "Unlimited Open Bar: 2 guests x $96".
- Real added cost for guests 3, 4 and 5 in the same category (fare and taxes).
- Full tables of every cabin on each ship for the current party. Unavailable cabins are greyed out with the reason: "Sold out", "Holds only X guests" or "Sold out for this party size".
- Guarantee categories (IX, OX, BX, MX) are labeled "Guarantee: NCL picks your cabin location".
- Daily cross checks in the data file: extra guest price consistency (logged) and fare plus taxes plus gratuities against NCL's price summary (fails the run when off by more than $5).
- The fetch script refuses any address containing "manage-cabin" or "hold".

### Changed
- `tools/fetch_prices.py` reads NCL's vacation-builder API (stateroom-types-availability and price-summary) and the route-events itinerary, with 2 seconds between calls, instead of the public sailing pages.
- Same cabin mode matches by broad type and defaults to the cheapest available category on each ship. Different cabins mode picks any available category on each ship.
- `tools/check_prices.py` checks the new data format.

### Removed
- CruiseFeed: the weekly cross check, the workflow option, the footer message and the repo secret steps.
- The "Includes about $200 per guest in taxes" notes and the "Free at Sea charge: not yet available" placeholder (both are now real lines).
- The "Estimated add-on" label (replaced by the real added cost).
- The 2 to 5 guest buttons (replaced by the adult and kid counters).
- The old Norwegian Joy CSV files (still in git history).

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
