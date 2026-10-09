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

## Cabin descriptions (4.1.0, researched 2026-10-07)

Goal: plain descriptions instead of codes, for example "Balcony, Decks 12 to 14 (BA)". Never guess a deck or location.

What NCL provides:
- The availability call's `stateroom` object (per group of codes): `title` (like "Family Balcony", "Aft-Facing Balcony", "Oceanview with Picture Window"), `categoryIds`, `deckLocations` (decks with Forward, Mid or Aft), `sizeInfo` (room and balcony square feet), descriptions and images.
- NCL groups several codes under one description. Getaway: Inside IB, IA, IC, IF; Balcony BB, BA, BF; Oceanview with Picture Window OA, OB; Family Oceanview O4, O5; Club Balcony Suite MB, MA. Aura: Inside IF, IB, IA; Balcony BF, BB, BA. For those, NCL's decks, location and size cover the whole group, not one code.
- The public pages say the same thing per group: `ncl.com/cruise-ships/norwegian-getaway/staterooms/options` ("Category IB, IA, IC, IF") and `ncl.com/cruise-ships/<ship>/deck-plans` (one entry per group with its decks and Forward, Mid, Aft). The Aura has no staterooms/options page (404). The deck plan legends only explain symbols; the per-deck plans are images (for example `Aura_Deck_14_01062026.png`), so per-code decks can't be read from NCL as text.

What Deck Finder provides (Getaway only, read only, `https://raw.githubusercontent.com/DASatizabal/deck-finder/main/ships/ncl/getaway/geometry.json`):
- Every cabin on decks 5 and 8 to 16 with its number, category code and position on the deck plan.
- Checked 2026-10-07: for every Getaway code, the decks in Deck Finder fall inside NCL's deck list for that code's group. So the per-code decks agree with NCL.
- Location is NOT derived from Deck Finder. Splitting each deck into front, middle and back thirds disagreed with NCL's own Forward, Mid, Aft labels for single-code groups (B4, HI, BT, M4), so that method is not reliable.

Rules in `tools/fetch_prices.py` (`describe_categories`), run on every refresh:
1. Description starts with NCL's title for the code.
2. If NCL's group has only that code: add NCL's decks, location and size (source "NCL").
3. If NCL's group has several codes: for the Getaway, add the code's decks from Deck Finder, only when they are inside NCL's deck list (source "Deck Finder (checked against NCL)"). No location and no size.
4. Guarantee cabins (IX, OX, BX, MX): no decks, no location, no size. The page says "Guarantee: NCL picks your cabin location".
5. When nothing else tells codes apart (the Aura's Inside IF, IB, IA and Balcony BF, BB, BA), add how many guests the cabin holds, from the 2-guest call. The Aura's BB and BA both hold 3, so only their prices differ.
6. If Deck Finder can't be read, the refresh still runs and those decks are left out that day.

## Layout changes (4.1.0)

- "Who is in the cabin": Adults counter, then Kids counter directly under it, then the kid age dropdowns.
- Cabin type is its own card below it.
- In each option card, the cabin selection lists (`div.card-picks`) sit between `div.card-head` and `div.card-body`. For the 3 and 5 night cards that is the list of categories in the chosen type. For the 8 night card it is the Same/Different toggle, then the category lists for both ships (Same) or the two cabin dropdowns (Different).

## Age rules (confirmed 2026-10-07 by price-summary tests on the AI PC, applied in 4.2.0)

Tests: Getaway B4, guests sent as `{"birthDate":"YYYY-MM-DD","reservationOwner":true or false}`, no names.

1. Fare is set by guest position, not age: positions 1 and 2 pay the base fare, position 3 and up pay the lower extra guest fare (Getaway B4: $299, $299, then $169).
2. Taxes are the same for every guest at any age.
3. Unlimited Open Bar gratuity:
   - 21 and over: full gratuity ($96 per guest on the Getaway, $160 on the Aura).
   - Under 21 in position 2 (only possible with 1 adult): $12.50 per day soda package, charged inside the same Open Bar line: $37.50 on the 3 night Getaway, $62.50 on the 5 night Aura. NCL's tooltip says under 21 guests receive a regular non-alcoholic beverage package. This applies at any age under 21, including a 7 year old.
   - Under 21 in position 3 or later: $0.
4. Specialty Dining gratuity: 13 and over pay, under 13 is free, in any position ($20 per guest on the Getaway, $40 on the Aura).
5. Test results (Getaway B4): 1 adult + 15 year old = $1,171.50; 1 adult + 15 + 7 = $1,540.50; 1 adult + 7 = $1,151.50; 2 adults + 15 + 7 = $1,988; 2 adults + 7 = $1,599. Reproduced from the cloud session on 2026-10-07 with the same results, and the page now shows exactly these totals.
6. Aura check from the cloud session: I4, 1 adult + 15 + 7 = $3,769.50 (fare $1,129, $1,129, $579; Open Bar $160, $62.50, $0; Specialty Dining $40, $40, $0; taxes $210 each).

Applied in 4.2.0:
- Page guest order: adults first, then kids oldest first. Kid ages are taken on Jun 11, 2027 (the Getaway's sail date); the dropdowns and a note under the Kids counter say so. A kid whose birthday falls between Jun 11 and Jun 14 could be one year older on the Aura; the page uses the Jun 11 age for both ships.
- The fetch script makes one extra price summary per ship (20 calls in all) with 1 adult (reservation owner), a 15 year old and a 7 year old, using birth dates 60 days before the sail date so the ages are exact. It reads the adult Open Bar, the soda package and Specialty Dining amounts from it, and stops the run if the amounts no longer follow the rules above.
- Age cross check (`checks.ages`): page formula for that party versus NCL's total, within $5, or the run fails.
- Rounding fix: NCL's availability average has cents (B4 at 3 guests: $455.66). `price_pp` now keeps the cents and `cabin_total` is rounded once, so it equals NCL's fare plus taxes ($1,367, not $1,368).
- The earlier NOTES line about the $12.50 soda package "not charged yet" is superseded by these rules.

## Publishing (4.3.0, researched 2026-10-07 and 2026-10-08)

Findings:
- GitHub Pages for this repo publishes from a branch today: every "pages build and deployment" run built `main`, and the live site at https://dasatizabal.github.io/cruise-cabin-comparison/ was byte-for-byte `main`'s top-level `index.html` (v2.5.0). `main` has no `docs` folder, so the folder is the root. `main` is not a protected branch.
- GitHub's docs (GITHUB_TOKEN page and the Pages publishing source page): "Commits pushed by a GitHub Actions workflow that uses the GITHUB_TOKEN do not trigger a GitHub Pages build." So with "Deploy from a branch", the daily data commits would never reach the family page.
- GitHub's docs on disabling workflows: "In a public repository, scheduled workflows are automatically disabled when no repository activity has occurred in 60 days." The docs don't define activity, so it's not documented whether the bot's daily commits count.
- The Pages docs don't say whether the currently published site stays live when the source is switched to GitHub Actions before a workflow deploys.

What was built:
- `.github/workflows/deploy-pages.yml` ("Deploy site"): on push to `main`, on demand (Run workflow), and as a reusable workflow. Checks out the commit, runs `tools/check_release.py`, copies `index.html` and `data/prices.json` into `_site`, then configure-pages, upload-pages-artifact and deploy-pages to the `github-pages` environment. The job only runs when the ref is `main`.
- `.github/workflows/refresh-prices.yml`: the `refresh` job outputs the commit it pushed (or the current commit when nothing changed); the `publish` job calls "Deploy site" with that commit, only on `main`; the `keepalive` job runs on scheduled runs on `main` and calls `gh workflow enable refresh-prices.yml` (needs `actions: write`; failures are ignored). Community keep-alive tools use this same API in their "no dummy commit" mode. It only helps while the workflow is still enabled, so the manual fallback is: Actions tab, "Refresh prices", "Enable workflow".
- Checked with actionlint 1.7.7: no problems.

Order for the switch (chosen so the family page relies only on documented behavior):
1. Merge the pull request first, while Pages still deploys from the `main` branch. The merge is a normal push by a person, so the branch build publishes the new page. The new "Deploy site" run on that push may fail, because Pages isn't set to GitHub Actions yet; that red mark is expected and harmless.
2. Right after, switch Settings, Pages, Source to "GitHub Actions".
3. Run "Deploy site" by hand once, so the next publish comes from GitHub Actions.
4. From then on, the daily refresh publishes the site itself.

## Cabin counts (4.4.0, 2026-10-08)

From the owner's AI PC test (plain requests, no cookies, no hold), confirmed from the cloud session:
- POST `https://www.ncl.com/api/vacation-builder/cabin/availability`, body `{"stateroomSearchFilter":{"stateroomTypeCode":"BALCONY","numberOfGuests":2,"pricedCategoryCode":"B4","accessibilityRequested":false,"filterId":"0","sailing":{"packageId":"24223992","shipCode":"GETAWAY","departureDate":"2027-06-11T00:00:00","destinationCodes":["BAHAMAS","WEEKEND"],"duration":3,"packageType":"CRUISE","sailingId":"60533"},"guests":[]}}`.
- The sailing part comes from the public GET `https://www.ncl.com/api/vacation-builder/itinerary/<itineraryCode>?packageId=<packageId>`: `ship.code`, `destinations[].code`, `duration`, `sailing.sailingId`, `sailing.sailStartDate`. Aura: AURA, ["CARIBBEAN"], 5, 62344, 2027-06-14T00:00:00. The fetch script reads these every run and checks packageId and date.
- The answer has `results.availablePositionInShip[]`: locations (Forward, Mid, Aft) with `numberOfCabins`, `lowestPriceCategory`, and `decks[]` with `cabins[]` (cabinNumber, deckNumber, shipLocation, shipSide, pricedCategoryCode, maxOccupancy, isADA, isGTY, extraPrice, price). It covers the requested category plus every pricier category of the same broad type.
- Cabin lists and deck `numberOfCabins` are capped at 15 per deck, so counts use only the location totals.
- Count for a category = its call's location totals minus those of the call for the next pricier non-Guarantee category (calls made from the most expensive down). Getaway Balcony at 2 guests: B4 call 139, B6 call 54, B1 call 30, so B4 85, B6 24, B1 30.
- No answer so far has contained "hold" or "heldUntil" (checked on every call; the run stops if one does).

Does numberOfGuests change the counts? Yes. Tested 2026-10-08: the Getaway B4 call returned 139 cabins at 2 guests and 97 at 4 guests (Aft dropped from 57 to 27, because B1 holds only 3 and some cabins can't take 4). So counts are fetched for every party size (2 to 5), only for categories available at that size: 141 calls on 2026-10-08 (74 Getaway, 67 Aura), about 19 minutes with the 2 second pauses (three calls timed out after 60 seconds and succeeded on retry).

Reliability rules (a count that fails one is stored as null and shows nothing):
- The call returned a location `lowestPriceCategory`, or a listed cabin, from another broad type. Seen on 2026-10-08: Getaway B6 (O4), MB (O4, O5), the Getaway Oceanview codes (MA, IA, B6), I4 (OA), IC (OX); Aura BB (O4), SK (M2). Deck-level `lowestPriceCategory` values are not used for this rule (the B4 call lists deck 9 Forward as O4 because its cabins are B6, which costs the same as O4).
- Two non-Guarantee categories of the same type have the same price for that party size (the subtraction order would be ambiguous). None on 2026-10-08.
- The subtraction is negative in a location or not positive in total. Seen: Getaway IF at 4 guests, Aura IF at 2 guests (0).
- 18 of 141 counts were unreliable on 2026-10-08. The list with reasons is in `checks.counts.unreliable` in the data file.

Descriptions from open cabins: for each category, the call at 2 guests lists its own open cabins (the category is the cheapest in its own call, so its cabins come first on each deck). Their decks and shipLocation fill a description's missing decks (the Aura's IB, IA, BF, BB, BA) and missing location (the Getaway's grouped codes). These describe where cabins are open now, so they can change from day to day. Nothing is filled when no open cabin of that code is listed (the Aura's IF on 2026-10-08).

Default cabin: every picker starts on the cheapest available non-Guarantee category; Guarantee categories stay in the lists.

## Resilience (4.4.0, 2026-10-08)

Two failures on `main` on 2026-10-08:
1. A manual "Refresh prices" run failed: NCL answered the availability POST with a 302, urllib followed it, and the new address gave 404. Fix: POST requests never follow redirects. A redirect, a 5xx or a network error is logged with the status code and Location header, then retried after 30, 60 and 120 seconds; after that the run fails. 401, 403 and 404 fail at once. Tested locally against a small test server (302 is never followed and fails after 4 tries; a 503 twice then 200 succeeds on the third try).
2. On the re-run, "publish / deploy" failed: upload-pages-artifact succeeded (artifact id 11552464267), and about a second later deploy-pages listed 0 artifacts: "No artifacts named github-pages were found for this workflow run."

Research on the deploy failure:
- actions/deploy-pages issue 451 (opened 2026-10-07, still open) describes the same pattern: upload-pages-artifact and deploy-pages in the same job, and the artifact listing comes back empty for an artifact finalized a fraction of a second earlier (62 of 63 runs worked). Its reporter fixed it by moving the upload into an earlier job, as GitHub's own Pages starter workflows do. https://github.com/actions/deploy-pages/issues/451
- The same issue explains that re-running cannot recover that layout, because the re-run uploads a second artifact with the same name and deploy-pages then fails with "Multiple artifacts named github-pages were unexpectedly found" (issue 338). https://github.com/actions/deploy-pages/issues/338
- deploy-pages v5 source (`src/internal/api-client.js`): it lists all artifacts of the run and filters by name, failing on 0 or more than 1 match. It has an `artifact_name` input. https://github.com/actions/deploy-pages
- Older reports of the same message were version mismatches between upload-pages-artifact and deploy-pages (issue 305, community discussion 84008); the versions here match. https://github.com/actions/deploy-pages/issues/305 and https://github.com/orgs/community/discussions/84008

Fix in "Deploy site":
- A `build` job runs the release check, collects `_site`, configure-pages and upload-pages-artifact. A separate `deploy` job runs deploy-pages, so the listing happens seconds after the upload, in another job.
- The artifact is named `github-pages-<run attempt>`, reported by the build job and passed to deploy-pages as `artifact_name`. "Re-run all jobs" uploads a new name instead of a second `github-pages`; "Re-run failed jobs" reuses the build job's name from the first attempt.
- The deploy step is retried once after 30 seconds if the first attempt fails.

Workflow maintenance: actions/checkout v7, configure-pages v6, upload-pages-artifact v5 (composite; it uses upload-artifact v7) and deploy-pages v5 all run on Node.js 24 (checked in each release's action.yml on 2026-10-08). Every job is pinned to `ubuntu-24.04`, so GitHub's change of `ubuntu-latest` can't change anything unexpectedly. actionlint 1.7.7 reports no problems.

## Counts separated from prices (4.5.0, 2026-10-09)

Owner decisions:
1. Prices stay daily and never depend on counts. The price fetch (itineraries, availability, price summaries, age test) keeps its schedule and publishes even if counts fail.
2. Counts move to their own job and their own file, `data/counts.json`, with its own `saved_at`. The counts job runs after the price job, commits its file, then publishes. If it fails or NCL refuses it, the prices still publish and the page keeps the last good counts.
3. Schedule: a full sweep (all categories, all party sizes) every 3 days; on the other days, re-check only categories whose last count was under 50, plus the next pricier category each one needs for the subtraction. 3 second pauses between count calls.
4. The page shows "Cabins left as of [date]" from `counts.json` and hides every count label when the file is missing or more than 7 days old.
5. `counts.json` has its own format check (`tools/check_counts.py`), so a bad counts file never blocks a price publish.

How it's built:
- `tools/fetch_prices.py` no longer makes cabin calls. `data/prices.json` no longer holds `cabins_left`, `count_reliable` or open-cabin details; `tools/check_prices.py` rejects them if they reappear.
- `tools/fetch_counts.py --prices data/prices.json --previous data/counts.json --out data/counts.new.json --mode auto|full|light`. It reads today's categories, prices and availability from `prices.json`. `auto` is full when there's no usable previous file (missing or failing `check_counts.py`) or the last full sweep was 3 or more UTC calendar days ago; light otherwise. Light mode starts from the previous entries for categories still available today, re-checks the reliable counts under 50 (and calls the next pricier category for each), and keeps every other entry with its own `checked_at`. Unreliable counts are only retried on full sweeps.
- Workflow "Refresh prices": `refresh` (prices) then `publish` (label prices); `counts` (`if: !cancelled()`, so it runs even if `refresh` failed, and checks out the branch head so it sees today's prices) then `publish-counts` (label counts); `keepalive`. Two publishes in one run use different artifact names (`github-pages-prices-<attempt>`, `github-pages-counts-<attempt>`), and the deploy job's concurrency group `pages` makes the second wait for the first.
- Manual runs: Actions, "Refresh prices", "Run workflow", then choose the cabin counts mode (auto, full or light). Pushes to the development branch always do a full sweep.
- How to tell the days apart: the counts commit message ends in "(full)" or "(light)"; `counts.json` has `mode`, `mode_reason`, `calls` and `last_full_sweep`; the counts job's log starts with "Mode: full (...)" or "Mode: light (...)".
- The page loads `counts.json` separately; any problem (missing, unreadable, wrong schema, more than 7 days old) hides the labels and the "Cabins left as of" date without touching prices. Descriptions are rebuilt on the page with the same rules as `fetch_prices.py`, filling missing decks or locations from `open_decks` and `open_locations` only while counts are fresh.

Volume (2026-10-08 data): a full sweep is 141 calls. 89 of those counts were under 50 (mostly small Haven, suite and Club Balcony categories), so a light day is about 100 calls including the subtrahend calls. Light days save roughly a quarter to a third of the calls; most of the saving comes from the 3 day full sweep cycle and the slower 3 second pace is a choice for gentleness, not speed.

## Free at Sea choices and gratuities (4.6.0, researched 2026-10-09)

Does the fare change when offers are declined? No. Price summaries for the Getaway Jun 11 sailing at 2 guests (cloud session, no cabin hold, no manage-cabin):
- B4 (Balcony): every Free at Sea promotion code NCL lists for the type gives the same fare, $299 per guest. ALL4CHO (all offers) $1,230 total = fare $598 + Open Bar $192 + Specialty Dining $40 + taxes $400. BVSXIN (Open Bar, Wi-Fi, excursions) $1,190: no dining line. DISXIN (Specialty Dining, Wi-Fi, excursions) $1,038: no Open Bar line. INTSHO (Wi-Fi, excursions) $998. BESTFARE and no fare code $998.
- HI (Haven): CHOALL4M $3,930, HSBVSXIN $3,890, HSINTSHO $3,698, all with a fare of $1,649 per guest. HSDISXIN returned an empty summary (all zeros), so it isn't usable.
- So turning off Open Bar or Specialty Dining only removes that gratuity. The page does this with the daily rates; it doesn't need extra calls.

Rates and their sources (read daily by `tools/fetch_prices.py`, stored in `rates` with `source` and `checked_at`):
- Free at Sea Plus, NCL promotion terms (https://www.ncl.com/cruise-deals/promotion-terms), "Prices are Per Person Per Day": guests 1 to 8 adult $49.99, guests 1 to 2 child $40 (USD). Terms: guests 2 and under are not eligible; 21 and over pay the adult rate; guests 1 and 2 aged 3 to 20 get the child version; guests 3 to 8 under 21 don't get it ("no substitutes, credits, or cash value"); all guests in a stateroom must choose the same offer. Plus includes "Prepaid Service Charge". The terms also say guests who already prepaid service charges get $15 ($20 child) off Plus; the page instead removes the service charge for Plus guests, which is the owner's rule.
- Open Bar gratuity, same terms page: $32 per person per day for 2 to 5 nights, $28.50 for 6 or more; Unlimited Soda package $12.50 per person per day. Cross check on 2026-10-09: the price summary amounts equal the rate x nights on both ships ($96 and $37.50 Getaway, $160 and $62.50 Aura).
- Specialty Dining: from the daily price summary age test ($20 Getaway, 1 meal; $40 Aura, 2 meals), with source and date. The terms page has no plain price table for it.
- Service charges, NCL FAQ (https://www.ncl.com/faq/what-is-onboard-service-charge redirects to https://www.ncl.com/faq/what-is-ncl-onboard-service-charge): "$25.00 USD per person per day for The Haven and Suites; $20.00 USD per person per day for Club Balcony Suite and below" (bookings on or after January 1, 2023), charged to "All guests 3 years or older", prepay up to 24 hours before sailing, adjustable onboard.
- The owner asked for the service charge "for every guest"; NCL's FAQ says guests 3 and older, so the page follows NCL and shows "(under 3: no charge)".

Page rules (4.6.0):
- Switches per cabin: Open Bar (on), Specialty Dining (on), Free at Sea Plus (off). For 8 nights, the Getaway and the Aura each have their own set. The 3 night card and the 8 night card share the Getaway's set, and the 5 night card and the 8 night card share the Aura's, because each is the same cabin booking.
- Free at Sea Plus on also turns Open Bar and Specialty Dining on, and turning either off turns Plus off. This follows the 2.x page's behavior (Plus is an upgrade of the Free at Sea beverage and dining offers); it is not separately confirmed in NCL's terms.
- Free at Sea Plus can't be priced through the price summary (it is not among the offer groups the availability call lists), so it is computed from the terms rates.
- Gratuities total = service charges + Open Bar gratuity + Specialty Dining gratuity. The prepay switch moves only the service charges between "Due before you sail" and "Charged onboard"; Free at Sea gratuities and Plus are always before sailing.

Light count days: re-check only counts under 15 (was under 50), plus the next pricier category each one needs. On the 2026-10-09 counts that is 58 counts and about 75 calls (it was 87 counts and about 94 calls at under 50; a full sweep is about 140). Most remaining small counts are Haven and suite categories.

NCL glitch seen 2026-10-09 around 02:00 UTC: the availability call for the Getaway at 4 and 5 guests marked categories available at a price of $0 (fare code ALL4CHO), and the price summary briefly returned a $0 total at 3 guests and $150 taxes at 4 guests. The Aura and the Getaway at 2 and 3 guests were normal. It lasted at least 15 minutes. The price fetch now retries such answers after 30, 60 and 120 seconds and then fails, so the last good prices stay published (counts still run). The committed `data/prices.json` for 4.6.0 is the last good fetch from 01:28 UTC with the rates read from NCL's pages at about 02:00 UTC.

## To do (not built yet)

1. Price drop and low availability email alerts to the owner, possibly through Resend.
2. A "Make Selection" button. When a family member has picked a trip and cabin, it opens a form for each guest's full name, date of birth, email address, Latitudes number if they have one, and anything else NCL needs to create a reservation, and sends it to the owner so the owner's NCL cruise consultant can book it. These are personal details and the repo and page are public, so the form must never store anything in the repo (or in the data files, or in browser storage beyond the open form). Options to weigh later: a button that opens the family member's own email app with everything filled in and addressed to the owner (nothing leaves their device except through their own email), or sending it through the owner's Cloudflare Worker by email (needs spam protection, for example the family passphrase).

## 4.7.0 findings (2026-10-09)

NCL $0 prices and the "Free 3rd & 4th Guest" idea:
- At 16:06 UTC the $0 prices were gone: every party size on both ships priced normally with fare code BESTFARE (Getaway 2: 32 categories, 3: 27, 4: 22, 5: 2; Aura 2: 28, 3: 20, 4: 16, 5: 3).
- The Getaway Jun 11 availability answer lists only the usual promotions (Free at Sea codes ALL4CHO, BVSXIN, CHOALL4M, HSBVSXIN, DISXIN, HSDISXIN, INTSHO, HSINTSHO; More Offers DISC50, 2-For-1 Deposits, Risk-Free Cancellation). Nothing in it mentions a free 3rd or 4th guest or kids sailing free.
- Price summaries now (fare per guest): B4 at 3 guests $299, $299, $169; at 4 guests $299, $299, $169, $169; O5 at 5 guests $329, $329, $159, $159, $159. Guests 3 and up pay a real (lower) fare, not $0.
- Conclusion: the $0 answers were a temporary NCL error, not a promotion. No badge. If NCL ever does switch on "Free 3rd & 4th Guest" for this sailing, the price summary's per guest fares would show $0 for guests 3 and 4; check that before adding the badge.

NCL tax change, 2026-10-09: taxes, fees and port expenses dropped by $50 per guest on both ships, Getaway $200 to $150 and Aura $210 to $160. The availability prices dropped by the same amount, and all formula and age checks match NCL exactly (Getaway B4 at 2 guests: price summary $890 total for the cheapest category IX, $1,250 on the page for 2 adults in B4 with service charges, Open Bar and dining).

Scheduled runs: as of 2026-10-09 16:06 UTC, GitHub had never started a scheduled "Refresh prices" run in this repository (the workflow is active, the file is on main, `schedule` runs total: 0). Expected runs on 2026-10-09 at 10:17 UTC did not happen. A GitHub staff note on a January 2026 community thread says any commit pushed to the default branch resyncs schedules that stopped firing (https://github.com/orgs/community/discussions/185212). The 4.6.0 merge at 15:57 UTC was such a push; the 2026-10-10 10:17 UTC run is the test. Sources on common causes: https://github.com/orgs/community/discussions/185355, https://steadycron.com/guides/github-actions-schedule-not-running/, https://latchkey.dev/learn/github-actions/github-actions-schedule-cron-default-branch-only. If it still never fires, fallbacks: run "Refresh prices" by hand, have the AI PC run `gh workflow run refresh-prices.yml` on a schedule, or ask GitHub Support with the repo, workflow path and cron line.

Free at Sea Plus coupling (kept on purpose): turning Free at Sea Plus on also turns on Open Bar and Specialty Dining, and turning either off turns Plus off. This comes from the 2.x page; NCL's terms describe Plus as an upgrade of Free at Sea but don't confirm this rule.

Per party size fallback (4.7.0): see CLAUDE.md, "Data". Tested locally on 2026-10-09 with simulated failures: one party size failing (Getaway 4 guests kept its earlier prices, run succeeded, file passed the format check), kept prices 8 days old (run failed), every party size failing on the Aura (run failed).
