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
7. Taxes and fees are per guest: Getaway $200, Aura $210, so the 8-night option is $410 per guest. Store these per sailing with a source and date. If NCL shows a different amount, use NCL's number and flag it.
8. The Free at Sea drink and food package is per guest and differs by ship. Find each ship's price on the NCL page. If it can't be found, leave it empty and say so. Do not guess.
9. Total for an option = cabin price for that party size + (taxes x guests) + (Free at Sea x guests), summed across both ships for 8 nights. Show taxes and Free at Sea as their own lines. Include cost per night.
10. Port: both ships are expected to use Terminal B (Pearl of Miami), NCL's dedicated PortMiami terminal. Try to confirm the terminal for each sailing from NCL's pages. If it can't be confirmed, show "Expected: Terminal B (confirm on your eDocs)" on the page.
