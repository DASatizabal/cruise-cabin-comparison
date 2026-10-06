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
