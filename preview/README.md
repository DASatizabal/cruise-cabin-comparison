# Preview copy (5.4.0, testing only)

A copy of `index.html` with test data, for a raw.githack.com preview of the branch pinned to a commit:
`https://raw.githack.com/DASatizabal/cruise-cabin-comparison/<commit>/preview/index.html`.

- `data/prices.json`: the owner-approved local live run of the new `tools/fetch_prices.py` on
  2026-11-15 (real NCL prices for 1 to 5 guests, schema 5).
- `data/counts.json`: main's counts of 2026-11-15 plus that day's live `fetch_counts.py --guests 1`
  run (real solo counts, regular cabins copying their 2 guest count; marked `only_guests`).
- "Deploy site" never publishes this folder, and `tools/check_release.py` fails while it exists:
  remove it before merging.
