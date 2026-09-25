# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## From the する gloss fix (migration 0019)

- **A kanji-written word is keyed by its standalone reading, not the one on
  the page.** `headword_reading` (`app/tokenization.py`) takes the page's
  reading from the token's `dictionary_form`, which fixed する (為る, なる →
  する) and kana spellings like いう and ワタシ. Where the dictionary form is
  itself the kanji spelling, the key still reads it on its own: 言う is keyed
  ゆう and 何 なん whatever the token reads. Both land on the same JMDict entry,
  so this is cosmetic as far as is known. Fixing it means keying an
  uninflected token by its own `reading_katakana`, then a 0019-style migration
  for the keys that change.
  *Sonnet 5, medium* — 0019 is the pattern to follow; what's left open is
  whether an inflected token can recover its citation reading.
