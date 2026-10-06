# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## Step 8 (song readiness and run-through)

- Sort the documents list by readiness, "least ready first" (§6). It has to be computed for every
  song before paging, in SQL or by loading all of the user's songs' units, so the sort and the page
  come from the same roll-up. Add `readiness` to `SortField` and make the header sortable.
  Model: Sonnet 5, medium effort — pattern work once the roll-up is chosen.
- Show the song's new readiness on the study session summary (§7, step 5): fetch
  `GET /documents/{id}/readiness` when a song session ends. Model: Haiku 4.5, low effort — one
  fetch and one list item.
