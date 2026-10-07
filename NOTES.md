# NOTES

## Lessons from Deck Finder

Briefing carried over from the Deck Finder project (public repo DASatizabal/deck-finder). Read that repo's CLAUDE.md, NOTES.md, and worker/worker.js for reference only. Do not modify it.

### CruiseFeed (verified in Deck Finder)

- Base URL `https://api.cruisefeed.io`, docs at `/docs`, schema at `/openapi.json`, Bearer auth.
- The plan is the FREE tier: 1,000 results total, one time, never resets. Ignore the Apify per-1,000 pricing.
- Free endpoints that cost 0 results: `/v1/ship-names`, `/v1/cruise-lines`, `/v1/stats`. Use them to get the exact `ship_name` strings and to check the remaining allowance.
- One sailing lookup costs 1 result. `include_delisted` and `include_past` options exist.
- The key is the Windows user environment variable `CRUISEFEED_KEY` on the AI PC, and a secret in the Cloudflare Worker. Never print it or put it in any repo file.

### Pattern already built in Deck Finder

- Cloudflare Worker at `deck-finder.dasatizabal.workers.dev`, passphrase protected, holds the CruiseFeed key.
- KV namespace `ITINERARIES` caches each sailing (key `itin:<line>:<ship>:<YYYY-MM-DD>`). Check KV first, call CruiseFeed only on a miss, store only public data plus `source` and `saved_at`.
- `tools/kv_put.py` seeds KV using secrets in `D:\AI-VAULT\secrets`.

### NCL website gotchas

- Fetching `ncl.com/cruises/<CODE>` needs the header `Accept: */*`. `Accept: text/html` redirects to a stripped page missing the embedded JSON.
- `/api/v2/vacations/search` returns 404 when called from Cloudflare.
- NCL removes sailings from its site once they stop selling.

### How the owner works

- Semantic Versioning, CLAUDE.md rules, CHANGELOG.md, and a GitHub Actions gate that blocks bad releases. Add a format check for any data file the page reads.
- Steps for the owner must be written out in full: no "same as above", no "if you want X" left to the owner, and no em dashes.
- Household phones are Android, but some family members use iPhones. Plain GitHub Pages links worked best for non-tech family.
- A 24/7 AI PC is available that can run a self-hosted GitHub Actions runner or scheduled Python jobs.

## Current project direction

- Turn this app into a decision guide that presents the family with three options, all NCL, all round trip from Miami:
  1. 3 nights: Jun 11 to Jun 14, 2027, Norwegian Getaway (Great Stirrup Cay, Nassau).
  2. 5 nights: Jun 14 to Jun 19, 2027, Norwegian Aura (Puerto Plata, Great Stirrup Cay, 2 sea days).
  3. 8 nights: both cruises back to back, Jun 11 to Jun 19, 2027. Leave the Getaway in Miami on the morning of Jun 14 and board the Aura that afternoon.
- The 8-night option is two separate bookings on two different ships, so its price is the sum of both. It still needs only the same 2 sailing lookups from CruiseFeed.
- Pull cabins, prices, and availability as close to real time as possible, using CruiseFeed without spending the free allowance carelessly.

## Decisions (owner answers)

### 1. 8-night cabin toggle

Add a toggle with two choices. Show the 8-night total for whichever choice is active.

- **"Same cabin on both ships"**: the family picks one cabin type, and the page matches it like for like on both ships: inside with inside, oceanview with oceanview, balcony with balcony, suite with suite, and Haven with Haven.
  - Mini-suite rule: if both ships have a mini-suite category, match mini-suite with mini-suite. If only one ship has a mini-suite, treat that mini-suite as a balcony for matching.
  - For each ship, show the specific NCL category the page matched.
  - If the chosen type is available for the chosen party size on one ship but not the other, say so plainly.
- **"Different cabin on each ship"**: the family picks a cabin for the Getaway and a separate cabin for the Aura, from each ship's own categories. Example: a suite on the Getaway and an inside cabin on the Aura.

### 2. Price refresh: option A (scheduled job on the AI PC), NCL as the primary source

Superseded on 2026-10-07: the refresh now runs as a GitHub Actions workflow on GitHub's own runners. See "Refresh plan" below. The AI PC is the fallback if NCL blocks GitHub's runners.

- Daily: read NCL's sailing page for each sailing (header `Accept: */*`). This is free.
- Weekly: call CruiseFeed for both sailings, 2-guest price only, as a cross check.
- Budget guard: call `/v1/stats` first. If remaining is below 150, skip CruiseFeed and log a warning in the data file. The allowance may already be well under 1,000, because Deck Finder used some.

### 3. Branch

- Do not merge to `main` yet. Keep working on `claude/cabin-selector-improvements-08QHA`. Merge once at the end.

### 4. Guests

- No fixed group. Add a guest selector for 2, 3, 4, or 5 guests per cabin.

## Pricing rules

5. Every cabin category must be checked at 2, 3, 4, and 5 guests. For each, record whether it is available and its price. Some categories only hold 2.
6. Record the price of guests 3, 4, and 5 separately from the first two, so the page can show the add-on cost.
7. Taxes and fees are per guest: Getaway $200, Aura $210, so the 8-night option is $410 per guest. Store these per sailing with a source and date. If NCL shows a different amount, use NCL's number and flag it. (Updated 2026-10-07: NCL's prices already include taxes. See decision 5 below.)
8. The Free at Sea drink and food package is per guest and differs by ship. Find each ship's price on the NCL page. If it can't be found, leave it empty and say so. Do not guess.
9. Total for an option = cabin price for that party size + (taxes x guests) + (Free at Sea x guests), summed across both ships for 8 nights. Show taxes and Free at Sea as their own lines. Include cost per night. (Updated 2026-10-07: taxes are not added on top, and Free at Sea is a placeholder. See decisions 5 and 8 below.)
10. Port: both ships are expected to use Terminal B (Pearl of Miami), NCL's dedicated PortMiami terminal. Try to confirm the terminal for each sailing from NCL's pages. If it can't be confirmed, show "Expected: Terminal B (confirm on your eDocs)" on the page.

## NCL probe results (2026-10-06, from a Claude Code cloud session)

- NCL did not block the cloud session. `/api/v2/vacations/search` and `/cruises/<CODE>` (header `Accept: */*`) both returned 200.
- Sailings found:
  - Getaway Jun 11 to Jun 14, 2027: itinerary `GETAWAY3MIANPINASMIA`, packageId 24223992, sailId 60533. NCL titles it "3-Day Bahamas Round-Trip Miami: Great Stirrup Cay & Nassau". Miami 4:00 PM, Great Stirrup Cay Sat 7:00 AM to 5:00 PM, Nassau Sun 7:00 AM to 5:00 PM, Miami Mon 7:00 AM.
  - Aura Jun 14 to Jun 19, 2027: itinerary `AURA5MIAPOPNPIMIA`, packageId 25729291, sailId 62344. Miami Mon 4:00 PM, sea day, Puerto Plata Wed 7:00 AM to 4:00 PM, sea day, Great Stirrup Cay Fri 8:00 AM to 5:00 PM, Miami Sat 7:00 AM.
  - The Getaway arrives in Miami at 7:00 AM on Jun 14 and the Aura sails at 4:00 PM the same day.
- Where the prices are: the `data-pricing-sailings` attribute on the cruise page (HTML-escaped JSON). Each sailing has `staterooms`, one per broad category (NCL calls these metas): `code`, `title`, `status` (`AVAILABLE`, `SOLD_OUT`, `NOT_AVAILABLE`), `price` (per person, after the current discount), `basePrice` (per person, before the discount).
- Categories on the page: Getaway has STUDIO, INSIDE, OCEANVIEW, BALCONY, MINISUITE ("Club Balcony Suite"), HAVEN. No SUITE category is listed for this Getaway sailing. Aura has STUDIO, INSIDE, OCEANVIEW, BALCONY, MINISUITE ("Club Balcony Suite"), SUITE, HAVEN. Both ships have a mini-suite, so mini-suite matches mini-suite.
- Specific categories (like "Family Balcony" or a category code like BA) are not on the cruise page. They live in NCL's booking app (`/booking`), which is a JavaScript app shell. Not probed further.
- Guests: add `?numberOfGuests=N` to the cruise page URL. The page then reports `guestCount` N and per person prices for N guests. `guestCount=N` works the same. One page fetch per guest count, so 4 fetches per sailing per day (8 total).
- The per person "from" price for a category can be a different specific cabin at a different guest count, because the cheapest cabin may not hold that many people. Seen: Getaway Oceanview went from $429 pp at 2 guests to $466 pp at 3. Aura Haven went from $2,602 pp at 3 to $2,799 pp at 4. So "cabin total at N minus cabin total at 2" is an estimate of the add-on cost, not an exact one.
- Taxes: the grid header says "PP / INCLUDES TAXES, FEES AND PORT EXPENSES". NCL's prices already include taxes, and the page does not itemize them. Adding $200 or $210 per guest on top would count taxes twice. Decided 2026-10-07: use NCL's price as the total and show the tax amount only as a note. Correction (2026-10-07, AI PC test): the sailing page bundles taxes, but NCL's booking API shows taxes as their own line ($200 per guest on the Getaway, $210 on the Aura). Version 4.0.0 shows that line.
- Free at Sea: the page lists the four offers (open bar, specialty dining, excursion credits, Wi-Fi) and says "Simply pay the package gratuities in advance", but gives no dollar amount for that per guest charge on either ship. Leave it empty until a source is found.
- Terminal: neither page names a terminal. `/api/cruises/v1/route-events/<packageId>` gives port times but no terminal. Show "Expected: Terminal B (confirm on your eDocs)".

## Booking flow probe (2026-10-06, Getaway Jun 11 at 2 guests, from a Claude Code cloud session)

No login, no reservation, no cabin hold. Not used by the daily job (decision 3 below). A separate local session on the AI PC is rerunning this in a real browser.

- The booking app is an Angular app at `https://www.ncl.com/booking`. Its calls are POST requests with JSON bodies to `https://www.ncl.com/booking/api/<name>`.
- The four calls tried:
  1. `vacation-availability`: works. Returns the sailing and a `state` object.
  2. `pricing`: works. Returns about 2 MB: every sailing of the itinerary from Oct 2026 to Nov 2027, with broad cabin type prices (`metaPrice[].price`, `basePrice`, `status`) and the list of specific categories (`subMetas[].code`). The specific categories have no prices.
  3. `meta-availability`: failed with HTTP 500 "An unexpected error happened" on three body shapes (`{"state":...}` with `metaId` set, and `{"sailing":..., "metaId":"BALCONY" or "OCEANVIEW" or "GETAWAY.BALCONY.R1-2020-rev23", "state":...}`). This is the call the app makes after picking a cabin type, and where specific category prices most likely come from.
  4. `quote`: failed with HTTP 400 "At least one of the required parameters is missing(metasSelection)". `metasSelection` is not in the app's code, so the server probably builds it from choices saved in the state by the earlier steps.
- State object: there is no session token. Each response returns `state`, and the next request sends it back in the body as `{"state": ...}`. The starting body that works for `vacation-availability`:
  `{"state":{"staterooms":[{"itineraryCode":"GETAWAY3MIANPINASMIA","numberOfGuests":2,"sailing":{"sailingId":24223992}}]}}`
  The returned state adds `shipCode`, `metaId`, `sailing.departureDate`, `sailing.departureDateFormatted` ("2027-06-11"), `selectedStateroomId` "1", `agencyId`, `userFareCodes` ["BF"] and `updatedProperties`.
- `sailingId` in the booking app is NCL's packageId (24223992 for the Getaway Jun 11 sailing), not the sailId (60533). Using no sailing, or the wrong id, returns error 42 "The date you selected is no longer available".
- `pricing` body: `{"guestSelections":[{"selectedStateroomId":"1","numberOfGuests":2}],"selectedMonthFilters":[],"state":<state>}`.
- Specific categories for the Getaway Jun 11 sailing (from `pricing`): Inside IA/IB/IC/IF, Family Inside I4, Solo Inside IT, Sailaway Inside IX; Oceanview with Picture Window OA/OB, Family Oceanview O4/O5, Solo Oceanview OT, Sailaway Oceanview OX; Balcony BA/BB/BF, Large Balcony B6, Family Balcony B4, Aft-Facing Balcony B1, Solo Balcony BT, Sailaway Balcony BX; Club Balcony Suite MA/MB, Club Balcony Suite with Larger Balcony M6, Family Club Balcony Suite M4, Aft-Facing Club Balcony Suite M1, Sail Away Club Balcony Suite MX; The Haven HF, HA, H7, H2, HI, H6, H3, HG; Studio T1 (not available).
- Bot protection: Akamai Bot Manager. The booking page sets the cookies `_abck` and `bm_sz` (plus `ak_*` location cookies and `akaas_www_ncl_com_as`). Nothing returned 403 or a challenge page. The app is built to send `X-XSRF-TOKEN`, but NCL never set an `XSRF-TOKEN` cookie, so none was sent.
- Where it failed: `meta-availability` (HTTP 500). The cause is unknown: a wrong body shape, a skipped step, or Akamai quietly refusing a client that never ran its sensor script. A real browser run that records the `meta-availability` and `quote` request bodies will tell.
- Avoid `api/recommended-cabin` (its config name is `recommendedCabinHoldUrl`, so it likely holds a cabin) and `api/book`.
- Free at Sea: no dollar amount for the per guest charge in any response. It most likely appears in `quote`. Correction (2026-10-07, AI PC test): the Free at Sea gratuities do have dollar amounts, in the vacation-builder price summary (see below).

## Decisions (2026-10-07)

1. Branch: keep working on `claude/cabin-selector-improvements-08QHA`. Do not merge to `main` until the owner says so.
2. Build the decision guide with broad cabin types only.
3. Do not use NCL's booking app in the daily job.
4. Do not write a Playwright script here. The AI PC session is running the booking flow test.
5. Taxes: use NCL's price as the total. Do not add taxes on top. Under each total show "Includes about $200 per guest in taxes" (Getaway), "Includes about $210 per guest in taxes" (Aura), "Includes about $410 per guest in taxes" (8 nights).
6. Add-on cost label: "Estimated add-on (NCL's cheapest cabin for that party size)".
7. Same cabin mode, Suite: the Getaway has no Suite on this sailing. Show "Not offered on the Getaway" and "Switch to Different cabins to pair an Aura Suite with any Getaway cabin."
8. Free at Sea: leave empty and show "Free at Sea charge: not yet available".
9. Hide Studio on both ships (it fits one guest).

## Refresh plan (built in 3.0.0, replaced in 4.0.0)

Superseded: 4.0.0 reads the vacation-builder API instead of the sailing pages, and CruiseFeed was removed. See "Version 4.0.0" below.

- `.github/workflows/refresh-prices.yml` on GitHub's own runners, not the AI PC.
- Daily (10:17 UTC): `tools/fetch_prices.py` loads both sailing pages at 2, 3, 4 and 5 guests (8 page loads, free) and writes `data/prices.new.json`.
- Weekly (Mondays, and manual runs with the box ticked): CruiseFeed cross check, 2-guest price only, only when the `CRUISEFEED_KEY` repo secret exists. It calls `/v1/stats` first and skips CruiseFeed when fewer than 150 results remain or the number can't be read. Then `/v1/ship-names` (free) to confirm the exact ship names, then one `/v1/cruises` lookup per sailing (2 results a week, about 9 a month). The result or warning is stored in the data file's `cruisefeed` block and shown in the page footer.
- `tools/check_prices.py` checks the new file. If it fails (bad format or a missing sailing), the workflow fails and `data/prices.json` stays as it was.
- The workflow commits `data/prices.json` every day, because `saved_at` changes even when prices don't. That keeps "Prices as of" honest.
- Scheduled runs only fire on the default branch (`main`), so the daily schedule starts after the merge. Until then, pushes to this branch that change the fetch tools or the workflow run it once, to test GitHub's runners.
- If NCL blocks GitHub's runners, fall back to the AI PC (a self-hosted runner or a scheduled Python job running the same script).

## Booking flow test on the AI PC (2026-10-07, run by the owner's local session, nothing committed there)

1. Availability: POST `https://www.ncl.com/api/vacation-builder/v2/stateroom-types-availability`, body `{"sailingFilters":[{"packageId":"24223992","numberOfGuests":2,"filterId":"0"}]}`. Returns every broad type with each specific category. Per category, under `results[0].result.stateroomTypesPricing[].stateroomsPricing[].categoryPricing[]`: `isAvailable`, `isSoldOut`, and `standardOption` with `pricedCategoryCode`, `guestCapacity`, and `price` (average per person, includes taxes, not Free at Sea gratuities).
2. When a category can't take the party, it stays in the list, `isAvailable` becomes false, `isSoldOut` stays false, `standardOption.guestCapacity` becomes 0, and `price` and `fareCode` are removed. No field says why. Whole broad types can switch off the same way at 5 guests.
3. Capacity: use `standardOption.guestCapacity` from the 2-guest call only, since it reads 0 whenever unavailable. Do not use `stateroom.guestCapacity` one level up; it is wrong for some categories (example: Getaway "Oceanview with Picture Window" says 5 there, but OA and OB hold 2).
4. Price summary: POST `https://www.ncl.com/api/vacation-builder/price-summary`, body `{"packageId":"24223992","stateroomFilters":[{"id":"0","mainCabin":true,"numberOfGuests":2,"stateroomTypeCode":"BALCONY","pricedCategoryCode":"B4","fareCodes":["ALL4CHO"],"guests":[],"vouchers":[]}],"userFareCodes":[]}`. Returns the fare, taxes per guest as their own line, Free at Sea gratuities per guest, and the total. Getaway B4: 2 guests $1,230 total, 3 guests $1,715. Getaway gratuities: Open Bar $96 per guest, Specialty Dining $20 per guest; excursion credits and Wi-Fi included.
5. Both calls work as plain requests with no browser and no cookies, and neither holds a cabin.
6. NEVER call `cabin/manage-cabin`. It carries recommendAndHold and puts a temporary hold on a real cabin. `tools/fetch_prices.py` refuses any address containing "manage-cabin" or "hold".

Confirmed from the cloud session on 2026-10-07:
- The Aura's packageId is 25729291: `route-events/25729291` starts on 2027-06-14 in Miami, and the availability and price summary calls accept it.
- Aura gratuities: Open Bar $160 per guest ($32 per day for 5 nights), Specialty Dining - 2 Meals $40 per guest. Aura taxes $210 per guest.
- Gratuities are the same for every cabin type on a ship (checked Getaway B4 and Haven HI, Aura IF and Haven HE).
- `fareCodes` matters. The default Free at Sea promotion per cabin type is in the availability answer's `offerGroups` (`FREE-AT-SEA` group, `isDefaultInGroup` true): ALL4CHO for Studio, Inside, Oceanview, Balcony and Club Balcony Suite; CHOALL4M for Suite and Haven. With `BESTFARE` the price summary leaves out Free at Sea entirely.
- The price summary also shows a per guest fare: on Getaway B4 at 3 guests the third guest's fare is $169 against $299 for guests 1 and 2.
- NCL's Open Bar text says: "Guests 1 or 2 under age 21 will instead receive juice and unlimited fountain soda for $12.50 per person per day. Guests 3 to 8 under 21 will not receive a beverage package." The page does not charge this yet (the owner's age rules apply until the kid pricing test is done). It only matters when a kid is guest 1 or 2, which happens with 1 adult and kids.
- Sold out categories (`isSoldOut` true) also read `guestCapacity` 0 at 2 guests, so their capacity is unknown (null in the data file) and their reason is "Sold out".

## Decisions (2026-10-07, second set)

1. CruiseFeed removed from this project: no weekly check, no workflow option, no footer message, no repo secret. NCL's own API provides everything needed, and the CruiseFeed allowance is saved for Deck Finder.
2. `tools/fetch_prices.py` uses the vacation-builder calls instead of the sailing pages: availability once per ship at 2, 3, 4 and 5 guests (8 calls), price summary once per ship per party size for the cheapest available category (8 calls), 2 seconds between calls.
3. Capacity and reasons: capacity from the 2-guest call. At N guests, unavailable and capacity below N: "Holds only X guests". Capacity N or more and still unavailable: "Sold out for this party size".
4. Daily cross checks, logged in the data file: extra guest price ((total at N minus total at 2) / (N minus 2) within $5 across 3, 4 and 5; log mismatches, keep the real per N numbers), and the formula check (average per person price x guests + gratuities x guests within $5 of the price summary total; fail the run if not).
5. Show specific categories under each broad type, cheapest first. Pickers show only available ones; the full tables show unavailable ones greyed out with the reason. Hide Solo and Studio (T1, IT, OT, BT). Label Guarantee categories (IX, OX, BX, MX) "Guarantee: NCL picks your cabin location". Show the real added cost for guests 3, 4 and 5 in the same category. Same cabin mode: match by broad type, default to the cheapest available category on each ship, tap to pick another. Different cabins mode: any available category on each ship.
6. Guests: "Adults (21+)" and "Kids (under 21)" counters, an age dropdown per kid (0 to 20), total 2 to 5 with at least 1 adult. Prices and fit use the total guest count. Gratuities per person: 21 and over pay Open Bar and Specialty Dining; 13 to 20 pay Specialty Dining only; 12 and under pay neither. Show who is charged for what. The AI PC session is testing whether NCL prices kids differently; an update may follow.
7. Each total shows its own lines: fare, NCL's tax line per ship, and each gratuity line. The tax notes and the Free at Sea placeholder are gone.
8. The old Norwegian Joy CSV files are deleted (git history keeps them).

## Version 4.0.0 refresh

- Daily on GitHub's runners (`.github/workflows/refresh-prices.yml`, 10:17 UTC once merged to `main`): 2 route-events calls, 8 availability calls, 8 price summary calls, 2 seconds apart, about 1 minute.
- The new file goes to `data/prices.new.json`; `tools/check_prices.py` checks it (including that every formula check passed); only then does it replace `data/prices.json`.
