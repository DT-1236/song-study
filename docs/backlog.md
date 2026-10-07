# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## `/simplify` on PR #74 (flashcards step 9)

- Store the picked JMDict entry, not just its spelling, in `katakana_picks`. A picked piece is
  looked up under `(spelling, reading)`, so a word with no kanji (spelled in kana) is looked up
  under its bare reading and shows whichever entry ranks first, and `word_options` dedupes by
  spelling, so two entries with the same usual spelling can't be told apart. Add an `idseq`
  column (0027 is unreleased, so it can change in place if nothing has migrated past it), return
  it from `word_options`, carry it on the picked piece, and have `_ranked_senses` keep only that
  entry's senses; `_spelling`'s `picked` special case then goes, since `_kanji_spelling` finds the
  right form. Model: Opus 5, high effort — touches the gloss cache's piece shape and the card
  key a pick produces, where a mistake is silent.
- Send each review as soon as it's answered and have a card correction undo it, instead of
  holding the answer in `StudyPage.tsx` until the card is left (which relies on `pagehide` for
  a closed tab). Needs `study_reviews` to keep the card's schedule from before each review, the
  review's id returned by `/review`, and `correct_card` to delete that review and restore the
  schedule when it's the card's latest. Model: Opus 5, high effort — a migration plus FSRS state
  restored exactly, where a mistake corrupts scheduling silently.

## `/simplify` on PR #75 (backlog sweep: low- and medium-effort items)

- Mark the token's current reading in the document page's "Look for other readings" list, and
  leave out the options `ReadingOptions` already shows above it. `get_alternate_readings` now
  returns the default reading and the token's own options too, so `AlternateReadingSearch`
  (`DocumentViewPage.tsx`) offers the current reading as a clickable option and its "No other
  readings found" note can't appear. Pass `isSelected` (the token's selected reading, by
  citation reading) and `canRepick={targets.length > 1}`, as `PieceWordPicker` does. Model:
  Sonnet 5, low effort.
- Stop a phrase's attached grammar from standing in for the phrase in the gloss popup.
  `document_words` lists it with `piece` None, since an accepted phrase's gloss isn't a
  composite, and `GlossPopup` takes the first word with no piece as the token's own, so when the
  phrase itself isn't studyable the popup offers the grammar term and adding it adds the phrase
  (or 422s). Give that grammar a piece, or leave it out of `document_words`; then `token_word`
  can find every word by `piece` alone instead of its two branches. Model: Opus 5, medium effort —
  which piece a phrase's grammar is depends on how `_apply_phrase_selection` glosses it, and a
  wrong piece links the wrong card silently.
- Add a non-partial index on `conflicts (token_id)`: only `WHERE selected` is indexed, so reading
  a token's conflicts (`get_alternate_readings`, `main.py`'s token reads) scans the table. New
  migration. Model: Haiku 4.5, low effort.
- In `cards._token_rows`, tie the `token_id` group subquery to `ANY(:document_ids)` rather than
  `t.document_id`, so Postgres runs it once rather than per grouped token. Model: Haiku 4.5, low
  effort.

## `/code-review` on PR #75 (backlog sweep: low- and medium-effort items)

- Count the song's new cards today after taking its lock in `study.song_queue`
  (`study.py`, the `FOR NO KEY UPDATE OF d` statement). The count is a subquery in the locking
  statement's select list, so under READ COMMITTED it's read from the statement's snapshot before
  the lock wait: when two session starts overlap, the second still sees the full limit and
  enrolls past it (20 new cards on a 10-a-day song). Take the lock in one statement, then count in
  a second. Add a test that forces the overlap with `BackgroundCall` and `wait_for_lock_wait`, as
  `test_overlapping_session_starts_both_get_every_card` does, and checks the total enrolled stays
  within the limit. Model: Opus 5, medium effort — the test has to pin the interleaving, and the
  fix depends on Postgres's snapshot rules.
- Skip gloss-cache work that grammar pieces don't need: `cards.token_word` calls
  `katakana_lookups` for any unit given a `piece`, katakana or not, and `_studyable` calls
  `gloss_sources` even when every key is grammar. Call `katakana_lookups` only when
  `unit[0].katakana_gloss` is set, and return early from `_studyable` when no non-grammar keys
  remain. Model: Haiku 4.5, low effort.
- Project JMDict's other readings onto an inflected token by the other reading's own conjugation.
  `glosses.alternate_reading_options` passes each through `project_citation_reading` with the
  token's conjugation type, which only handles 一段 and 五段 verbs and returns the citation
  reading unchanged otherwise: 来 of 来た (カ変) is offered きたる rather than きた, though 来る
  read きたる is 五段. Take the conjugation class from JMDict's part of speech for that reading
  (v5r for きたる), and leave out an alternate that still can't be projected rather than offering
  its citation form on an inflected surface. Add cases to `TestAlternateReadingOptions` in
  `test_glosses.py`. Model: Sonnet 5, medium effort — the projection exists for 一段 and 五段, but
  the conjugation class per reading has to come from JMDict's entry.
