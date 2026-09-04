"""SudachiPy-backed tokenization and furigana alignment for documents.

Pipeline per document:
  1. Tokenize with SplitMode.C (coarsest, closest to "word" granularity).
  2. For each token, align its Sudachi reading (katakana) against its surface
     text to produce per-span furigana, accounting for okurigana (kana in the
     surface anchors the reading; only kanji runs need ruby).
  3. Kanji runs of two or more characters have no anchor inside them, so the
     reading can't be positionally split without more work. We try (a) the
     SplitMode.A tokenization of the same span, in case it decomposes the run
     into independently-recognized words, then (b) a per-character dictionary
     reading lookup to brute-force a consistent split. If neither yields a
     single unambiguous split, we fall back to one span covering the whole
     run and flag the token for human review.
  4. Tokens are also flagged when Sudachi marks them out-of-vocabulary (kanji
     present, reading is a guess) or when the dictionary lists more than one
     reading for the exact same part-of-speech as the chosen token (a
     genuine heteronym Sudachi's own grammar can't disambiguate, e.g. 今日).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from sudachipy import dictionary as sudachi_dictionary
from sudachipy import tokenizer as sudachi_tokenizer

_KANJI_RE = re.compile(r"[㐀-䶿一-鿿々〆]")

_HIRA_TO_KATA = str.maketrans(
    {chr(code): chr(code + 0x60) for code in range(0x3041, 0x3097)}
)
_KATA_TO_HIRA = str.maketrans(
    {chr(code + 0x60): chr(code) for code in range(0x3041, 0x3097)}
)


def _to_katakana(text: str) -> str:
    return text.translate(_HIRA_TO_KATA)


def _to_hiragana(text: str) -> str:
    return text.translate(_KATA_TO_HIRA)


def _is_kanji(ch: str) -> bool:
    return bool(_KANJI_RE.match(ch))


_dictionary = None
_tokenizer = None


def _get_tokenizer():
    global _dictionary, _tokenizer
    if _tokenizer is None:
        _dictionary = sudachi_dictionary.Dictionary(dict="full")
        _tokenizer = _dictionary.create()
    return _tokenizer


@lru_cache(maxsize=4096)
def _char_readings(ch: str) -> frozenset[str]:
    """All katakana readings the dictionary lists for a single character."""
    tok = _get_tokenizer()
    return frozenset(m.reading_form() for m in _dictionary.lookup(ch))


def _partition_search(run: str, reading: str) -> tuple[Optional[list[str]], bool]:
    """Find a way to split `reading` into len(run) pieces, one per character
    in `run`, where each piece is a dictionary-known reading of that
    character.

    Returns (split, ambiguous). `split` is the unique split if exactly one
    was found, else None. `ambiguous` is True when more than one valid split
    exists (genuine disambiguation failure) as opposed to zero (the reading
    just isn't decomposable per-character, e.g. jukujikun like 今日).
    """
    n = len(run)
    solutions: list[list[str]] = []

    def backtrack(i: int, pos: int, pieces: list[str]) -> None:
        if len(solutions) > 1:
            return  # already know it's ambiguous, stop searching
        if i == n:
            if pos == len(reading):
                solutions.append(list(pieces))
            return
        readings = _char_readings(run[i])
        remaining_chars = n - i - 1
        max_len = len(reading) - pos - remaining_chars
        for length in range(1, max(max_len, 0) + 1):
            piece = reading[pos : pos + length]
            if piece in readings:
                pieces.append(piece)
                backtrack(i + 1, pos + length, pieces)
                pieces.pop()

    backtrack(0, 0, [])
    if len(solutions) == 1:
        return solutions[0], False
    return None, len(solutions) > 1


@dataclass
class FuriganaSpan:
    start: int
    end: int
    text: str
    reading: Optional[str]


@dataclass
class TokenRecord:
    position: int
    char_begin: int
    char_end: int
    surface: str
    dictionary_form: str
    normalized_form: str
    reading_katakana: str
    part_of_speech: list
    is_oov: bool
    furigana_spans: list
    needs_review: bool
    review_reason: Optional[str]


def _kanji_run_spans(
    run: str,
    run_reading: str,
    abs_start: int,
    a_mode_tokens: list,
) -> tuple[list[FuriganaSpan], bool]:
    """Split a single multi-character kanji run's reading across its
    characters. Returns (spans relative to run start, needs_review)."""

    # Try SplitMode.A first: if it independently recognizes sub-words inside
    # this run whose own readings add up to exactly run_reading, use those
    # boundaries (handles compounds Sudachi's C mode over-merged).
    abs_end = abs_start + len(run)
    sub_tokens = [
        t for t in a_mode_tokens if abs_start <= t.begin() and t.end() <= abs_end
    ]
    if len(sub_tokens) >= 2 and sub_tokens[0].begin() == abs_start and sub_tokens[-1].end() == abs_end:
        pieces = [t.reading_form() for t in sub_tokens]
        if sum(len(p) for p in pieces) == len(run_reading) and "".join(pieces) == run_reading:
            spans: list[FuriganaSpan] = []
            flagged = False
            offset = 0
            for t, piece in zip(sub_tokens, pieces):
                sub_run = t.surface()
                if len(sub_run) == 1:
                    spans.append(
                        FuriganaSpan(offset, offset + 1, sub_run, _to_hiragana(piece))
                    )
                else:
                    sub_spans, sub_flag = _kanji_run_spans(sub_run, piece, abs_start + offset, [])
                    for s in sub_spans:
                        spans.append(
                            FuriganaSpan(
                                offset + s.start, offset + s.end, s.text, s.reading
                            )
                        )
                    flagged = flagged or sub_flag
                offset += len(sub_run)
            return spans, flagged

    # Fall back to a per-character dictionary reading partition search.
    split, ambiguous = _partition_search(run, run_reading)
    if split is not None:
        spans = []
        pos = 0
        for ch, piece in zip(run, split):
            spans.append(FuriganaSpan(pos, pos + 1, ch, _to_hiragana(piece)))
            pos += 1
        return spans, False

    # No confident split: keep the whole run as one span. This is also the
    # linguistically correct outcome for non-decomposable (jukujikun)
    # readings like 今日 -> きょう, so only flag when a partition existed but
    # was ambiguous (multiple candidates), not when none existed at all.
    return [FuriganaSpan(0, len(run), run, _to_hiragana(run_reading))], ambiguous


def _build_furigana_spans(
    surface: str,
    reading_katakana: str,
    abs_start: int,
    a_mode_tokens: list,
) -> tuple[list[dict], bool]:
    if not _KANJI_RE.search(surface):
        return [{"start": 0, "end": len(surface), "text": surface, "reading": None}], False

    # Split surface into alternating kanji-run / other-run segments.
    segments: list[tuple[bool, int, int]] = []  # (is_kanji, start, end)
    i = 0
    while i < len(surface):
        is_k = _is_kanji(surface[i])
        j = i + 1
        while j < len(surface) and _is_kanji(surface[j]) == is_k:
            j += 1
        segments.append((is_k, i, j))
        i = j

    pattern_parts = []
    for is_k, start, end in segments:
        if is_k:
            pattern_parts.append("(.+?)")
        else:
            literal = _to_katakana(surface[start:end])
            pattern_parts.append(re.escape(literal))
    pattern = "^" + "".join(pattern_parts) + "$"

    match = re.match(pattern, reading_katakana)
    if match is None:
        # Reading doesn't literally align with the surface's kana (rare:
        # OOV guesses, unusual symbols like ヶ). Can't place furigana per
        # character; keep it as a single flagged span.
        return (
            [{"start": 0, "end": len(surface), "text": surface, "reading": _to_hiragana(reading_katakana)}],
            True,
        )

    spans: list[dict] = []
    flagged = False
    group_index = 1
    for is_k, start, end in segments:
        if not is_k:
            spans.append(
                {"start": start, "end": end, "text": surface[start:end], "reading": None}
            )
            continue

        run = surface[start:end]
        run_reading = match.group(group_index)
        group_index += 1

        if len(run) == 1:
            spans.append(
                {"start": start, "end": end, "text": run, "reading": _to_hiragana(run_reading)}
            )
            continue

        sub_spans, sub_flagged = _kanji_run_spans(run, run_reading, abs_start + start, a_mode_tokens)
        for s in sub_spans:
            spans.append(
                {
                    "start": start + s.start,
                    "end": start + s.end,
                    "text": s.text,
                    "reading": s.reading,
                }
            )
        flagged = flagged or sub_flagged

    return spans, flagged


def _heteronym_flag(surface: str, reading_katakana: str, pos: tuple) -> bool:
    try:
        candidates = _dictionary.lookup(surface)
    except Exception:
        return False
    readings = {
        m.reading_form() for m in candidates if tuple(m.part_of_speech()) == pos
    }
    return len(readings) > 1


def tokenize_document(text: str) -> list[TokenRecord]:
    tok = _get_tokenizer()
    mode_c = sudachi_tokenizer.Tokenizer.SplitMode.C
    mode_a = sudachi_tokenizer.Tokenizer.SplitMode.A

    a_mode_tokens = list(tok.tokenize(text, mode_a))
    records: list[TokenRecord] = []

    for position, m in enumerate(tok.tokenize(text, mode_c)):
        surface = m.surface()
        reading = m.reading_form()
        pos = tuple(m.part_of_speech())
        is_oov = m.is_oov()
        has_kanji = bool(_KANJI_RE.search(surface))

        furigana_spans, span_flag = _build_furigana_spans(surface, reading, m.begin(), a_mode_tokens)

        review_reason = None
        if has_kanji and is_oov:
            review_reason = "oov"
        elif has_kanji and _heteronym_flag(surface, reading, pos):
            review_reason = "heteronym"
        elif span_flag:
            review_reason = "no_kana_anchor"

        records.append(
            TokenRecord(
                position=position,
                char_begin=m.begin(),
                char_end=m.end(),
                surface=surface,
                dictionary_form=m.dictionary_form(),
                normalized_form=m.normalized_form(),
                reading_katakana=reading,
                part_of_speech=list(pos),
                is_oov=is_oov,
                furigana_spans=furigana_spans,
                needs_review=review_reason is not None,
                review_reason=review_reason,
            )
        )

    return records
