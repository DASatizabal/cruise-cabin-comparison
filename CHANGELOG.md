# Changelog

All notable changes to this project are listed here. Versions follow Semantic Versioning (MAJOR.MINOR.PATCH). The version in `index.html` (`APP_VERSION`) must match the newest entry below; `tools/check_release.py` enforces this.

## [5.2.0] - unreleased

Built on branch `family-tools-5.2.0` in the order the owner set: the DoubleUp watch, the payment data, Make Selection, then the price watch. This entry grows as each part is added.

### Added
- DoubleUp watch (alerts to the owner only). The daily price job reads NCL's CruiseNext page (https://www.ncl.com/cruise-deals/cruisenext) once, before the prices, with `tools/fetch_offers.py`: whether the "Limited-Time Offer: DoubleUp!" banner is there, its exact text, and the cabin types and time before sailing read from that text (today: Balcony and above, at least 90 days). Wording it can't read is saved as null with a warning and never guessed. A page that can't be read keeps the previous state with a warning, never fails the price run and never opens an issue.
- `data/offers.json` (schema 1, public NCL text, dates and codes only), committed with the prices, checked by the new `tools/check_offers.py` before it replaces the old file and in the release check, and published by "Deploy site".
- One GitHub issue per change (main only): "DoubleUp watch started" on the first run (to test that the alert reaches the owner's email and phone), then "appeared", "ended" or "text changed", with the old and new text, the Eastern date and the link. Each change has its own marker, so a retry never opens a second issue, and a change whose issue couldn't be opened is tried again on the next run. The issue mentions the owner, so GitHub notifies by email and on the phone.
- Release check workflow: actionlint (pinned Docker image `rhysd/actionlint:1.7.7`, with shellcheck) on every push and pull request.
- Tests: `tools/test_tools.py` (NCL's real banner markup saved 2026-10-28, every kind of change, one issue per change, retries, unreadable pages and wording, Eastern dates, the format check, and no em dash in any tracked file).

- Payment data in `data/prices.json` (schema 4), read from the price summaries and availability answers the job already makes (no extra NCL calls), for Make Selection:
  - per ship, `payment`: the final payment date (NCL's "pay in full" date: Feb 11, 2027 for the Getaway, Feb 14, 2027 for the Aura), the deposit NCL lists at each party size with its cabin type and hours to pay, the Inside to Club Balcony Suite deposit per guest ($50 today), and NCL's deposit offer as NCL words it ("2-For-1 Deposits" today);
  - `deposit_rules`: Suite and Haven deposits are 10% of the cruise fare (NCL's rule), confirmed daily on any Suite or Haven price summary the job makes (the Aura at 5 guests is a Haven today);
  - `checks.deposits`: every deposit read today against its rule. A check that fails never stops the run; the number it checks is left empty (null) with a warning, as with other missing numbers.
  - A notice per ship on the GitHub run page ("Deposits Getaway: $50 per guest up to Club Balcony Suite, ...").
- Tests: whole runs of `tools/fetch_prices.py` against a stand-in for NCL (same 26 calls as before, failed party sizes, kept prices from before 5.2.0, deposit checks that fail, dates that disagree, no deposit offer) and a saved NCL answer.

### Changed
- `data/prices.json` is schema 4. `tools/check_prices.py` checks the payment data; the release check still accepts the committed schema 3 file until the first refresh on main after the merge.

NCL calls: the price job goes from 26 to 27 a day (1 page load for the DoubleUp watch; the payment data adds none). Per week about 918 instead of 911 (940 instead of 933 in a week with the Florida light check). NOTES.md, "DoubleUp watch" and "Payment data".

## [5.1.0] - 2026-10-27

### Added
- Florida resident rate switch, first in the card now called "Florida resident rate and gratuities" (before the prepay switch), on by default and saved with the other choices, as on the Joy page. The page reads `data/florida.json` and works out from it whether NCL offers a discount, so nothing in the page changes when NCL's offer does:
  - No discount in the latest check: "Selected. NCL isn't offering a Florida resident discount on these sailings right now (checked Oct 27, 2026)." Totals are website prices.
  - A discount: each cabin's own dollar amount comes off the fare of guests 1 and 2, with a line in the total ("Florida resident rate (checked Oct 27): 2 guests x $60 off the fare"). Cabins the check didn't cover say "not checked for this cabin" and use the website price. The 8 night total uses each ship's own amount. A discount on one ship only is named under the switch.
  - A Florida fare above the website fare counts as no discount and is never added. Less than $1 per guest is rounding, not a discount.
  - Switch off: website prices, nothing extra.
  - "Florida rates as of [date]" at the top; amber after 9 days; after 15 days the file is not used and the switch says when prices were last checked. Without the file, the switch says Florida prices aren't available and website prices are shown.
- `tools/fetch_florida.py`: the weekly check on the owner's AI PC, from a separate clone that only pushes main (`tools/florida-runner/README.md`). A light check of 5 cabins per ship (cheapest Inside, Oceanview, Balcony, Club Balcony Suite and Haven; 22 NCL calls, 10 signed in) once a week; only if it finds a discount, every available cabin on both ships the same day (122 calls today, 60 signed in), repeated weekly while the discount lasts, then back to light checks. Runs that aren't due make no NCL calls. Eastern dates; nothing from Jun 11, 2027. Hold guard on every NCL answer, address check on every address, refuses to commit unless the Git email is the owner's noreply address, waits while Joy's task has the browser profile, never starts within 20 minutes of Joy's next run. Scheduled task "June Florida rates" at 9:00 AM, 1:00 PM and 5:00 PM.
- `tools/check_florida.py`: format check for `data/florida.json` (numbers, codes and dates only), run by the release check when the file is present. "Deploy site" publishes the file when present.
- Tests: `tools/test_tools.py` (cadence, runs against a stand-in for NCL with call counts, the hold guard on signed-in answers, the commit guard, the format check); `tools/page_test.py` (no discount, a Florida fare above the website, amber, unused, a discount on both ships and on one, 4 guests, switch off, 360 px).

NCL calls per week: about 911 before, 933 after with no discount, 1,033 while a discount is active (NOTES.md, "Florida resident rates").

## [5.0.1] - 2026-10-21

### Fixed
- A redirect from NCL crashed the run (UnboundLocalError in `request()`) instead of being retried. Since the hold guard was added in 5.0.0, the redirect branch fell through to the hold check with no answer. Redirects, 5xx and network errors are retried after 30, 60 and 120 seconds again, then the run fails with a clear message. Seen on the Oct 21 counts run: NCL answered cabin/availability with a 302 to ncl.com.mx. New offline test for it. 0 extra NCL calls.

## [5.0.0] - 2026-10-15

Improvements carried over from the Norwegian Joy page (DASatizabal/joy-cabin-compare 1.4.0), built on branch `june-joy-upgrades`. This entry grows as each part is added.

### Fixed
- Stale prices: "done that day" now means the Eastern date (America/New_York, the time zone, so daylight saving time is handled), not the UTC date, in `tools/decide_run.py` (timed runs: GitHub's schedule and the Cloudflare timer) and in `tools/fetch_counts.py` (3 day full-sweep cadence). A manual run on Oct 12 at 9:35 PM Eastern saved prices at 2026-10-13T01:36Z, which counted as Oct 13 by UTC date, so every timed run on Oct 13 skipped and the page had no refresh that day.
- A hold signal in the price fetch now stops the whole run. Before, the per party size and age test error handlers would have caught it and gone on with the other party sizes.

### Added
- Every refresh (prices and counts, timed and manual) stops from the first sail date, Jun 11, 2027 (Eastern).
- `tools/decide_run.py --now` sets the clock for tests (replaces `--today`).
- `tools/test_tools.py`: offline tests (no NCL calls), run by the release check workflow on every push: the Oct 12 evening case, same-day skips, the counts-only case, manual and branch runs, the days after daylight saving time ends on Nov 1, the sail-date stop, and the counts full-sweep cadence.
- Hold guard on every NCL API answer (availability, price summary, age test, route-events, itinerary, cabin availability), on top of the address guard and the counts job's older check, both kept as they were. It stops the whole run on a real hold signal: a key with "hold", "holds" or "held" as a word (`heldUntil`, `holdId`, `onHold`), a reservation ID key, or "hold" as a word (or "heldUntil") in a text value. Words like household, cardholder, placeholder and threshold never match. The one exception is NCL's "HOLD" payment option in price summaries (`staterooms[].paymentOptions[].paymentType`), which is logged and allowed; any other hold signal in the same answer still stops the run. 0 extra NCL calls.
- NCL's ids are looked up on every run, never typed in: for each ship, the cruise page gives the itinerary code and packageId of the sailing on our date, and NCL's itinerary call confirms the packageId, date, ship and length and gives the sailingId. If the cruise page can't be used, the previous run's ids are tried with a warning in the data file, and the itinerary call still has to confirm them. Only each ship, its date, its length and the Miami home port are fixed. The counts job takes the ids from today's price file and checks the ship code too. +4 NCL calls per price run (2 cruise pages, 2 itinerary calls).
- `data/prices.json` schema 3: `warnings` and `sailings[].ncl_ids`. The release check still accepts the schema 2 file on main until the first refresh after the merge; each new file must be schema 3.
- The price run shows the NCL ids it used, and any warning, as notices on the GitHub run's summary page.
- Tests for the hold guard on real hold signals, ordinary words and saved NCL answers (`tools/test_data/`: seven Getaway price summaries with the HOLD payment option, and the answer of a real `manage-cabin` hold).

- "Prices as of" shows the Eastern date and time of day, for example "Oct 15, 6:17 AM ET" (was the date only). 0 NCL calls.
- `tools/page_test.py`: the Chromium test at 360 px (Playwright, run locally): no sideways scrolling, no script errors, "Prices as of" in Eastern time across daylight saving time, and the "Not found on NCL today" rules on a copy of the data file with missing numbers.
- Missing numbers are never guessed: taxes, gratuities or rates NCL doesn't show today use the previous run's value within the same limits as the Joy page (gratuities up to 3 days old with a passing age check, rates at any age), else become null with a warning in the data file. The format check allows null only with a matching warning. The page shows "Not found on NCL today" on that line, leaves it out of the total, and says which items aren't included (with the ship's name on the 8 night card). Before, such a day failed the whole run. A missing tax line never takes taxes out of the total, because NCL's cabin price includes them: the tax line says "Included above" and the card says NCL didn't show the per-guest tax split today.

- Kids Sail Free: NCL's offer is read from the availability answers the price job already fetches (0 extra NCL calls), stored per sailing as `kids_sail_free` (null when NCL doesn't list it; format checked), and shown as one line under the total for the chosen cabin when NCL lists it for that ship and cabin type. The line says the 3rd and 4th guests pay only taxes, fees and port expenses only where that cabin's own NCL prices show it; otherwise it says NCL's prices charge them a fare. It never changes a total. The price run shows whether NCL lists it, as a notice on the GitHub run's summary page.
- `tools/florida_proof.py`: a manual, one-time check (14 NCL calls, 6 signed in) of whether June's fares differ when signed in to a Florida resident NCL account. Writes and commits nothing; never scheduled. First run 2026-10-15: all 6 cabins $0 different, so June's Florida rates (item 9) are on hold and the "prices moved" warning (item 10) doesn't apply.

### Removed
- The "Added cost in [cabin] (fare and taxes): guest 3 +$X, guest 4 +$X" line under each card's total (Getaway, Aura and both ships on the 8 night card), as on the Joy page. Totals and everything else on the cards are unchanged; `added_vs_2` stays in `data/prices.json`. 0 NCL calls.

### Changed
- The prepay gratuities switch is off by default, like the Joy page. With it off, every total is what's paid now, without service charges ("Total to pay now"), with "+ $X service charges paid onboard (can be removed at Guest Services)" under the total; the service charge line is grey and marked onboard; the 8 night card adds both ships' service charges. With it on, totals include them, as before. The "Due before you sail" and "Charged onboard" lines were removed. Switch off: "Prepay gratuities (No)", "Pay onboard on the last day. Service charges are not in the totals. They're charged to your onboard account and can be removed at Guest Services." Switch on: unchanged. 0 NCL calls.
- Saved choices moved to the key `cruise-decision-guide-v5`. Choices saved under the old key are carried over once (guests, kid ages, cabins, Free at Sea) with the prepay switch reset to the new default.
- NCL's promotion terms page is read once per run instead of twice, like the Joy code: the price job is 26 NCL calls (it was 23 before 5.0.0, not 22 as first written here, and 27 after the id lookup).
- Commit messages "Refresh prices DATE" and "Refresh cabin counts DATE" use the Eastern date.
- The workflow's branch test trigger moved to `june-joy-upgrades`.
- Branch test runs (pushes to the development branch) fetch prices only and skip counts: about 26 NCL calls per push instead of about 165 with a full counts sweep. Counts run on a branch only from a manual run with a chosen count mode. Branch runs still never commit data or publish.

## [4.10.0] - 2026-10-12

An outside timer for the daily refresh, because GitHub's schedule has been unreliable for this repo.

### Added
- `tools/refresh-trigger/worker.js`: a small Cloudflare Worker (separate from the Deck Finder Worker) with cron triggers at 10:20 and 15:05 UTC. Each one asks GitHub to start "Refresh prices" on main with source "timer", using a fine-grained token stored only as the Worker secret `GITHUB_TOKEN`, and logs GitHub's answer. Visiting the Worker's address only returns a short message.
- `tools/refresh-trigger/README.md`: steps to create the token, set up the Worker in the Cloudflare dashboard, test it, and check it the next morning.
- "Refresh prices" workflow_dispatch input `source` (manual or timer). Timer runs use the same skip logic as scheduled runs, are titled "Refresh prices (timer)", and run the keepalive job. Manual runs still always run fully.

### Changed
- The GitHub schedule times (10:17, 14:47, 19:37 UTC) stay as backups.
- NOTES.md: the GitHub schedule history for this repo (the 10:17 slot never fired on time; other runs came 1 to 7 hours late; none by 17:16 UTC on Oct 12).

## [4.9.2] - 2026-10-10

### Changed
- Free at Sea Plus line, in every Free at Sea set: "Adds unlmt. Wi-Fi\\top shelf spirits\\Starbucks\\bottled water\\daily svc. chrg. $[adult rate]/adult/night." with a literal backslash between items and the adult rate from the data file. Checked on the rendered page: the backslashes show as typed. It takes 2 lines at 360 px wide.

## [4.9.1] - 2026-10-10

### Changed
- Shorter Free at Sea lines so they fit on a phone. Under the switches: "Premium spirits, 100+ cocktails, sodas and juices, plus drinks at Great Stirrup Cay."; "[N] specialty restaurant meal(s) per guest, about a $40 to $60 value each." (N from each ship's price summary); "Adds unlimited Wi-Fi, top shelf spirits, Starbucks, bottled water, and all crew gratuities. $[adult rate] per adult per night." (rate from the data file).
- Below the switches, three lines in this order: the under 21 and under 13 rules, "Always included: 150 minutes of Wi-Fi per guest and a $50 excursion credit per port for guest 1.", and "Choose at least 24 hours before sailing. No changes onboard."
- Measured at 360 px wide: every line takes 2 lines except the Free at Sea Plus line, which takes 3.

## [4.9.0] - 2026-10-10

Free at Sea explained in short lines instead of a table.

### Added
- A "See NCL's full drink list (PDF)" link above each set of Free at Sea switches, opening NCL's 2026 Beverage Packages Flyer in a new tab.
- One short line under each Free at Sea switch in every option card: what Unlimited Open Bar includes and the under 21 rules; Specialty Dining meals per guest (1 on the Getaway, 2 on the Aura, each ship's own number in the 8 night card); what Free at Sea Plus adds, with the adult rate per night from the data file.
- Under the switches: "Always included: 150 minutes of Wi-Fi for each guest, and a $50 shore excursion credit per port of call for guest 1." (confirmed on NCL's promotion terms, 2026-10-10) and "Choices must be made at least 24 hours before sailing and can't be changed onboard."

### Removed
- The "What's included?" comparison table, which was too wide and too much at once on a phone.

### Notes
- NOTES.md records the flyer's fine print, including its "Unlimited open bar at Great Stirrup Cay (where applicable)" wording under Free at Sea Plus, and the owner's firsthand finding that Great Stirrup Cay drinks were included with regular Free at Sea Open Bar (Getaway, Oct 2, 2026). All charges still come from NCL's live price summaries.

## [4.8.0] - 2026-10-09

Backup times for the daily refresh, because GitHub's scheduled runs can be late or dropped.

### Added
- "Refresh prices" now also runs at 14:47 and 19:37 UTC (10:47 AM and 3:37 PM Miami time), besides 10:17 UTC.
- A first job, `decide` (`tools/decide_run.py`), for scheduled runs: if `data/prices.json` and `data/counts.json` were both saved today (UTC date of `saved_at`), the run ends right away as a success and skips the price, counts and publish jobs; if prices were saved today but counts were not, only counts run. It shows which case applied as a "Refresh decision" notice on the run's summary page. Manual runs and branch test runs always run fully. The keepalive job still runs on every scheduled run.
- NOTES.md: how to tell from the Actions tab which scheduled time did the work and which ones skipped; a To do item for triggering the refresh from the Cloudflare Worker or the AI PC if GitHub schedules stay unreliable.

### Fixed
- Merged `main` into the branch again. The first scheduled run (Refresh prices #13, on main) had committed new data files, so `data/prices.json` and `data/counts.json` conflicted. Main's newer versions were kept (prices saved 2026-10-09T17:00:33Z, counts saved 2026-10-09T17:00:40Z, light). Main's price file was written by the 4.6.0 code, so the `party_sizes` block the format check needs was added (every party size updated, as of 17:00:33Z). Both pass their format checks.

## [4.7.1] - 2026-10-09

### Fixed
- Branch test runs of "Refresh prices" no longer commit `data/prices.json` or `data/counts.json`. They still fetch and run both format checks, then stop; only runs on `main` commit data files. This stops the branch's data files from conflicting with `main`'s, which made GitHub report that the branch couldn't merge automatically.
- Merged `main` into the branch. `data/prices.json` and `data/counts.json` conflicted (main's 16:10 UTC manual refresh against the branch's 16:16 UTC test run); the newer branch versions were kept and both pass their format checks.

## [4.7.0] - 2026-10-09

### Added
- Per party size fallback in the daily price fetch. If one party size on one ship fails its checks, that ship and party size keep the previous prices, the page marks them "Not updated today" with the date they are from, and everything else refreshes and publishes. The run fails only if every party size on a ship fails, or if kept prices would be more than 3 days old. `data/prices.json` records this per sailing in `party_sizes` (`updated`, `as_of`, `why`); the format check covers it. The age test keeps the previous gratuities the same way.
- Aura badge in Option 2 and Option 3: "🍾 Maiden Voyage from Miami 🎆", a short note about her christening, and a "Watch: Meet Norwegian Aura" link.
- "What's included?" under each set of Free at Sea switches: a Free at Sea versus Free at Sea Plus comparison (Unlimited Open Bar, Specialty Dining, Wi-Fi, service charges), with the Plus daily rates and the service charge rates taken from the data file. The columns stack on a phone.

### Changed
- The formula cross check now uses each price summary's own gratuity lines, so each party size is checked on its own before it is used.
- 8 night explainer: "you get off the Getaway" instead of "you leave the Getaway".

### Notes
- NCL's $0 prices for the Getaway at 4 and 5 guests (2026-10-09 early UTC) were gone by 16:06 UTC. No "3rd and 4th guest free" promotion is listed for this sailing and guests 3 to 5 pay real fares, so no promotion badge was added.
- NCL lowered taxes, fees and port expenses by $50 per guest on 2026-10-09: Getaway $200 to $150, Aura $210 to $160. Cabin prices dropped by the same amount.

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
