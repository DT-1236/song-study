# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## `/simplify` on document processing step 3 (text changes reset processing by trigger)

- **LRCLIB line timings are cleared by hand when the text changes.**
  `update_document_text` in `backend/app/main.py` sets `lrclib_lines = NULL`
  with the new text. A future text writer (the timing editor or upload PRs)
  that forgets this keeps timings for the wrong text. The trigger from
  migration 0034 can't own it, since `_store_lrclib_lyrics` writes a new
  text and new lines together. Instead, stale-check them on read the way
  `edited_lines` is (`CASE WHEN edited_lines_text = text` in
  `backend/app/db.py`): a new `lrclib_lines_text` column set where the lines
  are written, a backfill, and the `CASE` in `DOCUMENT_COLUMNS`. One
  migration plus two writers. Sonnet 5, medium: the pattern to copy is
  right there, but the backfill and the `_linked_lyrics` match rule need
  care.
