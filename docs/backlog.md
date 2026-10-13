# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## `/simplify` on document processing step 5 (polls read before locking)

- **A claiming request reads the document's state twice.** `start` in
  `backend/app/processing.py` reads it without a lock, then locks the row
  and reads it again before its `UPDATE`, so first processing went from 16
  to 17 round trips. One conditional `UPDATE … WHERE` (not processed, no live
  claim, not failed unless `retry`) `RETURNING text, processing_started_at`
  could replace the locked read and the lock. On 0 rows, re-read to say
  which state stopped it. Update the counts in
  `test_first_processing_takes_a_fixed_number_of_round_trips`. Opus 5,
  medium: the claim races the job's release, and a wrong `WHERE` processes a
  document twice or never, without any error.
