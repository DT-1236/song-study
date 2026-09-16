"""Suggest combining consecutive tokens into one longer JMDict headword (an
idiom like この/期/に/及ん/で -> この期に及んで, whose 期 reads ご only in the
idiom).

Only ever suggested for review, never applied: an exact headword match can be
a coincidence, like 今日/は spelling こんにちは or し/たく spelling したく.
"""

from __future__ import annotations

from app.glosses import phrase_prefix_state, resolve_phrase_reading
from app.grammar import attached_end
from app.tokenization import TokenRecord

# JMDict's multi-word entries are a handful of words long at most, so this
# bounds the scan from each start.
MAX_PHRASE_TOKENS = 8

# Content words only: a scan starting at a particle or auxiliary mostly finds
# unrelated headwords. Particles are still fine inside a match (この期に及んで).
_PHRASE_START_POS = frozenset(
    {"名詞", "動詞", "形容詞", "形状詞", "副詞", "連体詞", "感動詞", "代名詞", "接頭辞"}
)

_PREDICATE_POS = frozenset({"動詞", "形容詞", "形状詞", "助動詞"})


def _can_start_phrase(part_of_speech) -> bool:
    return part_of_speech[0] in _PHRASE_START_POS


def find_phrase_suggestions(records: list[TokenRecord]) -> None:
    """Set phrase_suggestion on each of `records` that starts a JMDict
    headword spanning several tokens: the headword, its reading, how many
    tokens it covers (phrase_token_count), and how many the suggestion
    covers with the grammar attached after it (token_count, 真に受け +
    てみて)."""
    n = len(records)
    for i in range(n):
        if not _can_start_phrase(records[i].part_of_speech):
            continue
        # A match starting inside a predicate group, or not reaching past
        # the one it starts, is only that group's own words, often by
        # coincidence: した ("tongue"), しまった ("oops").
        group_start = records[i].phrase_start_position
        if group_start not in (None, records[i].position):
            continue
        group_end = i
        while group_start is not None and group_end < n and records[group_end].phrase_start_position == group_start:
            group_end += 1

        current = records[i].surface
        best_end: int | None = None
        best_candidate: str | None = None
        for j in range(i + 1, min(i + MAX_PHRASE_TOKENS, n)):
            # An inflected last token can only complete a headword through
            # its dictionary form: 真に受け is 真に受ける's stem, never the
            # headword itself.
            if records[j].dictionary_form != records[j].surface:
                citation_candidate = current + records[j].dictionary_form
                if phrase_prefix_state(citation_candidate)[0]:
                    best_end = j + 1
                    best_candidate = citation_candidate

            current += records[j].surface
            is_exact, has_longer = phrase_prefix_state(current)
            if is_exact:
                best_end = j + 1
                best_candidate = current
            if not has_longer:
                break

        if best_candidate is None or best_end <= group_end:
            continue
        # Resolved only for the longest match, since reading lookups hydrate
        # whole entries.
        reading = resolve_phrase_reading(best_candidate)
        if reading is None:
            continue

        end = best_end
        if records[best_end - 1].part_of_speech[0] in _PREDICATE_POS:
            end = attached_end(records, best_end)
        records[i].phrase_suggestion = {
            "surface": "".join(r.surface for r in records[i:end]),
            "lookup_form": best_candidate,
            "reading": reading,
            "token_count": end - i,
            "phrase_token_count": best_end - i,
        }
