# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## From `/simplify` on PR #24 (users, ownership, Google login)

- **Handle a 401 centrally in the frontend's `apiFetch`.**
  `AuthGate` checks `/auth/me` once, at load, so a session that expires mid-use
  surfaces as per-call error text. `apiFetch` could catch a 401 and send the
  browser back to the login page (or reset the gate's state).
  *Sonnet 5, medium* — conventional React against a clear behavior.

## From flashcards step 2 (card storage and harvest)

- **Every する is glossed as なる, "to become".**
  A gloss key's reading is taken from the token's *normalized* form
  (`citation_key` in `app/glosses.py`: `mixed_reading(normalized_form)`), and
  Sudachi normalizes する to 為る, which read on its own as a kanji word comes
  back as なる. The kana the token was actually written in (する, in
  `dictionary_form` and `reading_katakana`) is lost by then. So the reading
  view glosses every する (and a predicate group's する head) under entry
  1375610 "to become" instead of 1157170 "to do", and the step 2 harvest
  copies that key into a card, (為る, なる). The same derivation picks the
  rarer reading of the right word elsewhere (言う → ゆう, 私 → わたくし,
  何 → なん), which is only cosmetic, but 為る is the one where it lands on a
  different word.
  The fix is to take the citation reading from what's written on the page
  wherever the normalized form alone gives a different word, and it isn't
  local: the same `mixed_reading(normalized_form)` feeds `citation_key` and
  its callers (`gloss_key`, `own_gloss_key`, `_group_pieces`/`_piece_sources`
  for helper verbs, `app/katakana.py`), the default conflict option's
  `citation_reading` (`app/conflicts.py:72` and `:903`), the `no_kana_anchor`
  options (`app/tokenization.py:723`) and `tokenization.py:157`. Stored data
  carries the wrong key too: `gloss_lookups` rows keyed (為る, なる), tokens
  linked to them, predicate-group composites built on them, and the
  `citation_reading` inside existing conflict rows. So it needs a migration in
  the 0013–0015 style (unlink and drop the affected glosses, rewrite the stored
  citation readings) as well as the code change. Better done before step 3
  starts scheduling cards, since any card already enrolled under (為る, なる)
  would be orphaned with its history once the key changes.
  *Opus 5, high* — it changes the gloss cache key used across the app, and a
  wrong key fails silently as a plausible-looking gloss for a different word.
  Deciding which normalized forms need the page's reading, and repairing the
  stored conflict values, both still have to be worked out.

## From adding Prettier and Ruff (formatting only)

- **Narrow the blind `except` in `heteronym_readings`.**
  `app/tokenization.py` catches bare `Exception` around a SudachiPy lookup and
  returns `[]`. That's the right fallback — it runs per token while tokenizing,
  and "no heteronym readings" is a fine answer — but as written it also
  swallows a real bug. Narrowing it needs a list of what SudachiPy's `lookup`
  actually raises, which is why the Ruff adoption left it with a `# noqa` and
  a comment rather than guessing.
  *Sonnet 5, medium* — the work is finding out what that library raises; the
  edit itself is one line.
