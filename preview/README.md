# Preview copy (5.4.0, testing only)

A copy of `index.html` with test data, for a raw.githack.com preview of the branch pinned to a commit:
`https://raw.githack.com/DASatizabal/cruise-cabin-comparison/<commit>/preview/index.html`.

- `data/prices.json`: today's prices with 1 guest prices shaped like NCL's answers in the probe of
  2026-11-15 (`tools/test_tools.py`, `schema5`), until the local live run gives real ones.
- `data/counts.json`: today's counts with 1 guest entries (`one_guest_counts`).
- "Deploy site" never publishes this folder, and `tools/check_release.py` fails while it exists:
  remove it before merging.
