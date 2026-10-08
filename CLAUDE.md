# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A decision guide that helps the family choose between three Norwegian Cruise Line options from Miami in June 2027:
1. 3 nights: Norwegian Getaway, Jun 11 to Jun 14 (Great Stirrup Cay, Nassau). NCL packageId 24223992.
2. 5 nights: Norwegian Aura, Jun 14 to Jun 19 (Puerto Plata, Great Stirrup Cay, 2 sea days). NCL packageId 25729291.
3. 8 nights: both back to back, changing ships in Miami on Jun 14.

The page is `index.html` (HTML, CSS and JavaScript in one file). It reads `data/prices.json`. Background, decisions and probe findings are in `NOTES.md`; read it before changing pricing logic.

## Rules

- Semantic Versioning. `APP_VERSION` in `index.html` must match the newest `## [x.y.z]` entry in `CHANGELOG.md`. Add a changelog entry for every release.
- Run `python3 tools/check_release.py` before committing. GitHub Actions runs it on every push and pull request.
- Any data file the page reads needs a format check (today: `tools/check_prices.py` for `data/prices.json`).
- NEVER call NCL's `cabin/manage-cabin` (it carries recommendAndHold and holds a real cabin), `api/book`, `booking/api/recommended-cabin`, or anything that holds or books. `tools/fetch_prices.py` refuses any address containing "manage-cabin" or "hold". Keep that guard.
- Steps written for the owner must be complete: no "same as above", no choices left open, and no em dashes.
- Family members use Android and iPhone. Keep the page working at phone width.
- CruiseFeed is not used in this project (its allowance is saved for Deck Finder).

## Data (`data/prices.json`, schema 2)

Written by `tools/fetch_prices.py` from NCL's vacation-builder API, plain POST requests with no cookies, 2 seconds apart:
- `https://www.ncl.com/api/cruises/v1/route-events/<packageId>` (GET): day by day itinerary; also confirms the departure date.
- `https://www.ncl.com/api/vacation-builder/v2/stateroom-types-availability`, body `{"sailingFilters":[{"packageId":"24223992","numberOfGuests":2,"filterId":"0"}]}`: one call per ship per party size 2 to 5.
- `https://www.ncl.com/api/vacation-builder/price-summary`: one call per ship per party size, for the cheapest available category, to read the tax line and the Free at Sea gratuity lines. `fareCodes` must be the default Free at Sea promotion for that cabin type (ALL4CHO for Inside to Club Balcony Suite, CHOALL4M for Suite and Haven), read from the availability answer's `offerGroups`. With BESTFARE the summary leaves out Free at Sea.
- One more price summary per ship (the age test): guests 1 adult (`reservationOwner` true), a 15 year old and a 7 year old, sent as `{"birthDate":"YYYY-MM-DD","reservationOwner":...}` with no names, for the cheapest category at 3 guests.
- `https://www.ncl.com/api/vacation-builder/itinerary/<itineraryCode>?packageId=<packageId>` (GET): sailingId, shipCode, destination codes, duration and departure date for the cabin call.
- `https://www.ncl.com/api/vacation-builder/cabin/availability` (POST, `stateroomSearchFilter`): one call per ship per party size per available non-Guarantee category, most expensive first, for cabins left and where open cabins are. About 160 calls per run in all, about 20 minutes. The run stops if an answer mentions "hold" or "heldUntil".
- POST requests never follow redirects; redirects, 5xx and network errors are retried after 30, 60 and 120 seconds.

File layout:
- `saved_at` (UTC), `guest_counts` [2, 3, 4, 5], `checks` (`formula`: one entry per ship per party size, all must be `ok`; `ages`: one entry per ship for 1 adult + 15 + 7, must be `ok`; `counts`: `calls` and the `unreliable` counts with reasons; `extra_guest_mismatches`: logged only).
- `sailings[]`: `id`, `ship`, `ship_short`, `itinerary_code`, `package_id`, `depart`, `return`, `nights`, `url`, `taxes_per_guest`, `gratuities` (`open_bar`: `title`, `per_guest` for 21 and over, `soda_under_21_position_2`, `under_21_position_3_plus` 0; `specialty_dining`: `title`, `per_guest` for 13 and over, `under_13` 0), read daily from an age test price summary, `terminal`, `ports`, `price_summaries`, `types[]`.
- Each type: NCL code (STUDIO, INSIDE, OCEANVIEW, BALCONY, MINISUITE, SUITE, HAVEN), `title`, `match`, `categories[]`.
- Each category: `code` (pricedCategoryCode, like B4), `title`, `guarantee`, `solo`, `capacity` (from the 2-guest call only, null when unknown), and `by_guests` "2" to "5": `available`, `sold_out`, and when available `price_pp` (average per person with NCL's cents, includes taxes, not gratuities), `cabin_total` (`price_pp` x guests, rounded to whole dollars; equals NCL's fare plus taxes), `added_vs_2`, `cabins_left` (whole number, or null for Guarantee and unreliable counts) and `count_reliable`; when unavailable a `reason` ("Sold out", "Holds only X guests", "Sold out for this party size").
- Each category also has a plain `description` (shown instead of the code), `decks`, `location` (forward, midship, aft), `size`, `details_source` and `shares_ncl_description_with`. Rules (see NOTES.md, "Cabin descriptions"): NCL first; NCL's decks, location and size are used only when NCL's group has that one code; for the Getaway, per-code decks come from the owner's public Deck Finder repo (`ships/ncl/getaway/geometry.json`, read only) and are kept only when they fall inside NCL's deck list; never guess a deck or location; Guarantee cabins list no decks. Gaps (missing decks or location) are filled from NCL's list of the category's own open cabins at 2 guests.

## Pricing logic (in `index.html`)

- Guest order is NCL's: adults first, then kids oldest first. Fare is set by position (cabin_total already covers it) and taxes are the same at any age.
- Total for a ship = `cabin_total` for the party + Open Bar per guest (21 and over full; under 21 in position 2 the soda package; under 21 in position 3 or later nothing) + Specialty Dining per guest (13 and over pay; under 13 free). Kid ages are taken on Jun 11, 2027. Lines shown: cruise fare (`cabin_total` minus taxes), taxes (`taxes_per_guest` x guests), each gratuity line with "N guests x $X", total, per person, cost per night. 8 nights = both ships added.
- Cabin prices and which categories fit use the total number of guests (adults plus kids). Party size 2 to 5, at least 1 adult.
- Added cost for guests 3 to 5 = the real difference between party sizes in the same category.
- Same cabin mode matches by broad type (mini-suite rule in `NOTES.md`) and defaults to the cheapest available category on each ship; the family can tap another. A type missing on one ship shows "Not offered on the <ship>" and "Switch to Different cabins to pair an <ship> <type> with any <ship> cabin." Different cabins mode picks any available category on each ship.
- Default cabin in every picker: the cheapest available non-Guarantee category, or the cheapest Guarantee one when that's all a type has.
- Cabins left labels: 50 or more "Plenty left", 10 to 49 "Getting low", under 10 "Only X left"; nothing for Guarantee or unreliable counts.
- Hide Studio and Solo categories (T1, IT, OT, BT). Label Guarantee categories (IX, OX, BX, MX) "Guarantee: NCL picks your cabin location". Pickers show available categories only; the full tables show unavailable ones greyed out with the reason.

## Automation

- `.github/workflows/refresh-prices.yml`: daily at 10:17 UTC (scheduled runs only fire on `main`), manual runs, and pushes to the development branch that touch the fetch tools. The new file is written to `data/prices.new.json`, format checked, and only then replaces `data/prices.json`.
- `.github/workflows/refresh-prices.yml` also has a `publish` job (calls `deploy-pages.yml` with the new data commit, only on `main`) and a `keepalive` job (scheduled runs on `main` only: `gh workflow enable refresh-prices.yml`, never fatal).
- `.github/workflows/deploy-pages.yml` ("Deploy site"): GitHub Pages source is "GitHub Actions". Publishes only `index.html` and `data/prices.json` (in `_site`), after the release check, on push to `main`, on demand, or when called by the refresh. Never publishes another branch. Commits made with `GITHUB_TOKEN` don't trigger Pages builds, so every automated data change must go through this workflow.
- `.github/workflows/check.yml`: release gate.
- Every job runs on `ubuntu-24.04` (pinned). Actions are on their Node.js 24 majors: checkout v7, configure-pages v6, upload-pages-artifact v5, deploy-pages v5.
- "Deploy site" has a `build` job (release check, `_site`, upload with artifact name `github-pages-<run attempt>`) and a `deploy` job (deploy-pages with that name, retried once after 30 seconds). Keep upload and deploy in separate jobs (deploy-pages issue 451).
