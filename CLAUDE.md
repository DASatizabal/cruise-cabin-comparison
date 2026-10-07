# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A decision guide that helps the family choose between three Norwegian Cruise Line options from Miami in June 2027:
1. 3 nights: Norwegian Getaway, Jun 11 to Jun 14 (Great Stirrup Cay, Nassau).
2. 5 nights: Norwegian Aura, Jun 14 to Jun 19 (Puerto Plata, Great Stirrup Cay, 2 sea days).
3. 8 nights: both back to back, changing ships in Miami on Jun 14.

The page is `index.html` (HTML, CSS and JavaScript in one file). It reads `data/prices.json`. Background, decisions and probe findings are in `NOTES.md`; read it before changing pricing logic.

## Rules

- Semantic Versioning. `APP_VERSION` in `index.html` must match the newest `## [x.y.z]` entry in `CHANGELOG.md`. Add a changelog entry for every release.
- Run `python3 tools/check_release.py` before committing. GitHub Actions runs it on every push and pull request.
- Any data file the page reads needs a format check (today: `tools/check_prices.py` for `data/prices.json`).
- Never print or commit the CruiseFeed key. It lives only in the `CRUISEFEED_KEY` repo secret (and on the owner's AI PC).
- Steps written for the owner must be complete: no "same as above", no choices left open, and no em dashes.
- Family members use Android and iPhone. Keep the page working at phone width.

## Data (`data/prices.json`)

Written by `tools/fetch_prices.py` from NCL's public sailing pages (`https://www.ncl.com/cruises/<ITINERARY_CODE>?numberOfGuests=N`, header `Accept: */*`). The prices sit in the page's `data-pricing-sailings` attribute.

- `saved_at` (UTC), `guest_counts` [2, 3, 4, 5], `cruisefeed` (last weekly cross check: `status`, `remaining`, `warning`, per sailing results).
- `sailings[]`: `id`, `ship`, `ship_short`, `itinerary_code`, `package_id`, `depart`, `return`, `nights`, `url`, `ports` (day by day), `taxes_per_guest_estimate` (owner estimate, shown only as a note), `free_at_sea_per_guest` (null until a source is found), `terminal`, `categories[]`.
- Each category: NCL's broad cabin type `code` (STUDIO, INSIDE, OCEANVIEW, BALCONY, MINISUITE, SUITE, HAVEN), `title`, `match` key, and `by_guests` for "2" to "5": `status`, `available`, and when available `price_pp`, `base_pp`, `cabin_total` (= `price_pp` x guests) and, for 3 to 5 guests, `addon_vs_2` (cabin total minus the 2-guest cabin total).

## Pricing logic (in `index.html`)

- NCL's prices are per person and already include taxes, fees and port expenses. Do not add taxes on top. Show "Includes about $200 per guest in taxes" (Getaway), "$210" (Aura), "$410" (8 nights).
- Option total = `cabin_total` for the chosen party size. 8 nights = Getaway total + Aura total. Per person = total / guests. Cost per night = total / nights.
- Add-on for guests 3 to 5 is labeled "Estimated add-on (NCL's cheapest cabin for that party size)", because NCL's cheapest cabin of a type can change with the party size.
- Same cabin mode matches like for like. Mini-suite rule: if both ships have a mini-suite, match them; if only one does, the other ship uses its Balcony. A type missing on one ship shows "Not offered on the <ship>" and, when the other ship has it, "Switch to Different cabins to pair an <ship> <type> with any <ship> cabin."
- Studio is hidden (it fits one guest). Free at Sea shows "not yet available".

## Automation

- `.github/workflows/refresh-prices.yml`: daily at 10:17 UTC (scheduled runs only fire on `main`), manual runs, and pushes to the development branch that touch the fetch tools. Mondays and manual runs with the box ticked also run the CruiseFeed cross check when the secret exists (skipped below 150 remaining results). The new file is written to `data/prices.new.json`, format checked, and only then replaces `data/prices.json`.
- `.github/workflows/check.yml`: release gate.

## Old files

`cabin_base_price_*.csv` and `cabin_prices_table_with_oceanview.csv` are from the Norwegian Joy version (2.x) and are not read by the page.
