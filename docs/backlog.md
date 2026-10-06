# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## `/simplify` on the kanji map beside the queue (`kanji.py`, `card_content.py`, `main.py`)

- The sidebar's five-word limit lives only in the backend (`MAX_DECK_WORDS` in `kanji.py`, which
  `deck_cards` sends one more than), so step 6's UI would hardcode a matching 5 to slice after
  leaving out its own `card_id`, and the two can drift. Send the limit in `StudyQueue` (or have the
  UI own it and the backend take it as the query's cap) when step 6 builds the sidebar. Sonnet 5,
  low — a constant threaded through one response model.
