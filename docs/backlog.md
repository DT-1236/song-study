# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## `/simplify` on PR #54 (linking a katakana line's words to their cards)

- **Store whether a katakana piece is attached, not just its unit.**
  `_katakana_card_tokens` (`backend/app/cards.py`) decides a grammar piece is
  attached to a word by its unit having more than one piece, a proxy that
  holds only because a composite base's pieces never carry a
  `normalized_form`. `_add_katakana_readings` (`backend/app/glosses.py`)
  already knows which pieces it builds with `_attached_piece`, so it can store
  `"attached": true` on them, and the card rule reads that instead of counting
  units. Changes the stored shape, so it needs a migration clearing the
  katakana composites as 0025 does; drop `"unit"` only if nothing else reads it.

  Sonnet 5, low: the rule and where to set the flag are both settled.
