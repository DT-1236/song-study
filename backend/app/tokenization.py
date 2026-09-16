"""SudachiPy-backed tokenization and furigana alignment for documents.

Pipeline per document:
  1. Tokenize with SplitMode.C (coarsest, closest to "word" granularity).
  2. Ask Sudachi itself whether this C-mode token is a merge of independently
     recognized words: `morpheme.split(SplitMode.A)` returns the finer-grained
     decomposition when one exists (e.g. 勝利の女神, one C-mode token, splits
     into 勝利/の/女神), or nothing when the token is already irreducible at
     Sudachi's finest granularity. This gives correct word boundaries
     directly — including across a kana particle in the middle of a
     kanji-heavy span, which no amount of regex alignment on the merged
     surface could recover, since that boundary information only exists on
     the morpheme itself.
  3. For each piece (the whole token if it didn't decompose, or each
     SplitMode.A sub-word otherwise), align its reading against its surface
     to produce per-span furigana, accounting for okurigana (kana in the
     surface anchors the reading; only kanji runs need ruby).
  4. A kanji run of two or more characters with no kana anchor inside it
     (e.g. 勝利 on its own) still can't be positionally split — Sudachi
     doesn't decompose within a single word. A per-character dictionary
     reading lookup brute-forces a consistent split; if more than one valid
     split exists, all of them are kept as alternatives for a human to pick
     from (see conflict_options on TokenRecord), and if none exists the run
     falls back to one span covering the whole run.
  5. Tokens are also flagged when Sudachi marks them out-of-vocabulary (kanji
     present, reading is a guess) or when the dictionary lists more than one
     reading for the exact same part-of-speech as the chosen token (a
     genuine heteronym Sudachi's own grammar can't disambiguate, e.g. 今日) —
     each alternate reading becomes a conflict_options entry too.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import NamedTuple, Optional

from sudachipy import dictionary as sudachi_dictionary
from sudachipy import tokenizer as sudachi_tokenizer

_KANJI_RE = re.compile(r"[㐀-䶿一-鿿々〆]")

_HIRA_TO_KATA = str.maketrans(
    {chr(code): chr(code + 0x60) for code in range(0x3041, 0x3097)}
)
_KATA_TO_HIRA = str.maketrans(
    {chr(code + 0x60): chr(code) for code in range(0x3041, 0x3097)}
)


def to_katakana(text: str) -> str:
    return text.translate(_HIRA_TO_KATA)


def to_hiragana(text: str) -> str:
    return text.translate(_KATA_TO_HIRA)


def _is_kanji(ch: str) -> bool:
    return bool(_KANJI_RE.match(ch))


@lru_cache(maxsize=1)
def _get_dictionary() -> sudachi_dictionary.Dictionary:
    return sudachi_dictionary.Dictionary(dict="full")


@lru_cache(maxsize=1)
def _get_tokenizer():
    return _get_dictionary().create()


@lru_cache(maxsize=4096)
def citation_reading(dictionary_form: str) -> str:
    """The katakana reading Sudachi gives dictionary_form when tokenized on
    its own, i.e. the word's citation-form reading (揃える -> ソロエル), as
    opposed to reading_katakana on some inflected token derived from it
    (揃え -> ソロエ). JMDict keys entries by citation form + citation
    reading, so gloss lookups need this, not a token's own reading."""
    tok = _get_tokenizer()
    mode_c = sudachi_tokenizer.Tokenizer.SplitMode.C
    return "".join(m.reading_form() for m in tok.tokenize(dictionary_form, mode_c))


@lru_cache(maxsize=4096)
def _char_readings(ch: str) -> frozenset[str]:
    """All katakana readings the dictionary lists for a single character."""
    return frozenset(m.reading_form() for m in _get_dictionary().lookup(ch))


@lru_cache(maxsize=4096)
def conjugation_type_of(word: str) -> str:
    """The conjugation-type tag (part_of_speech[4]) Sudachi gives `word`
    when tokenized standalone, e.g. '五段-マ行' for 挟む, '下一段-マ行' for
    挟める. Empty if `word` doesn't tokenize as a single morpheme."""
    tok = _get_tokenizer()
    mode_c = sudachi_tokenizer.Tokenizer.SplitMode.C
    morphemes = list(tok.tokenize(word, mode_c))
    if len(morphemes) != 1:
        return ""
    return morphemes[0].part_of_speech()[4]


_GODAN_TO_POTENTIAL = {
    "ウ": "エ", "ク": "ケ", "グ": "ゲ", "ス": "セ", "ツ": "テ",
    "ヌ": "ネ", "ブ": "ベ", "ム": "メ", "ル": "レ",
}


def _is_regular_potential_form(dictionary_form: str, dictionary_form_conjugation: str, normalized_form: str) -> bool:
    """True if dictionary_form is the grammatically regular potential form
    of the godan verb normalized_form (挟める <- 挟む: "to be able to X").

    Requires a genuine ichidan/godan conjugation-class switch between the
    two forms, not just a reading match — that's what distinguishes 挟める/
    挟む from a lexicalized look-alike like キレる/切れる, which are both
    already ichidan with no class switch at all.
    """
    # Both must hold: dictionary_form's own paradigm is ichidan,
    # normalized_form's is godan, and the reading follows the regular
    # godan -u -> -eru pattern.
    if not dictionary_form_conjugation.startswith(("上一段", "下一段")):
        return False
    if not conjugation_type_of(normalized_form).startswith("五段"):
        return False
    base_reading = citation_reading(normalized_form)
    potential_reading = citation_reading(dictionary_form)
    if not base_reading or base_reading[-1] not in _GODAN_TO_POTENTIAL:
        return False
    expected = base_reading[:-1] + _GODAN_TO_POTENTIAL[base_reading[-1]] + "ル"
    return potential_reading == expected


def dictionary_form_note(dictionary_form: str, normalized_form: str, conjugation_type: str) -> Optional[str]:
    """A short, learner-facing note when dictionary_form and normalized_form
    differ — the gloss shown to the user is looked up under normalized_form,
    so it's worth explicitly surfacing that the text's actual dictionary
    form is a different (if related) word. None when they're the same."""
    if dictionary_form == normalized_form:
        return None

    dict_reading = mixed_reading(dictionary_form)
    norm_reading = mixed_reading(normalized_form)

    if _is_regular_potential_form(dictionary_form, conjugation_type, normalized_form):
        return (
            f"{dictionary_form}（{dict_reading}）is the potential form of {normalized_form}"
            f"（{norm_reading}）, meaning \"can {normalized_form}\" — the definitions below are for"
            f" {normalized_form} itself and don't show that nuance."
        )

    return (
        f"{dictionary_form}（{dict_reading}）is this token's exact dictionary form, but Sudachi"
        f" treats it as a variant of {normalized_form}（{norm_reading}）, which the definitions"
        f" below are looked up under."
    )


def _partition_search(run: str, reading: str) -> list[list[str]]:
    """All ways to split `reading` into len(run) pieces, one per character in
    `run`, where each piece is a dictionary-known reading of that character.

    Empty means the reading isn't decomposable per-character at all (a
    whole-word/jukujikun reading like 今日 -> きょう). More than one means a
    genuine disambiguation choice: multiple valid per-character splits, and
    no way to know which one is intended without a human picking.
    """
    n = len(run)
    solutions: list[list[str]] = []

    def backtrack(i: int, pos: int, pieces: list[str]) -> None:
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
    return solutions


@dataclass
class FuriganaSpan:
    start: int
    end: int
    text: str
    reading: Optional[str]


class KanjiRunResult(NamedTuple):
    spans: list[FuriganaSpan]
    needs_review: bool
    alternatives: list[list[FuriganaSpan]]


class FuriganaResult(NamedTuple):
    spans: list[dict]
    needs_review: bool
    alternatives: list[list[dict]]


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
    conflict_options: list
    # The position of the first token of the group this token is merged into.
    phrase_start_position: Optional[int] = None
    # A phrase found starting here (see app.phrase_merge), to offer for
    # review. Not stored on the token.
    phrase_suggestion: Optional[dict] = None


def conflict_option_value(reading: str, furigana_spans: list[dict], citation_reading: str) -> dict:
    """The shared shape for a conflict's `value` JSONB column: one candidate
    reading, its furigana display, and the JMDict-keyed citation reading
    gloss lookups need. Built in one place so the three keys don't drift
    between the call sites that construct one — the auto-flagged
    heteronym/no_kana_anchor options here, and the default/manual-correction
    options in app/conflicts.py."""
    return {"reading": reading, "furigana_spans": furigana_spans, "citation_reading": citation_reading}


def _kanji_run_spans(run: str, run_reading: str) -> KanjiRunResult:
    """Split a single multi-character kanji run's reading across its
    characters. Returns (spans relative to run start, needs_review,
    alternatives) — alternatives is a list of alternative full-run span
    lists to offer as a redo-able choice, populated only when more than one
    valid per-character split was found.
    """
    # Only called for a run Sudachi couldn't already decompose into
    # independent words (see module docstring) — no boundary information
    # is left to exploit, so this falls back to a brute-force per-character
    # dictionary partition search instead.
    solutions = _partition_search(run, run_reading)
    if solutions:
        chosen = solutions[0]
        spans = [
            FuriganaSpan(i, i + 1, ch, to_hiragana(piece))
            for i, (ch, piece) in enumerate(zip(run, chosen))
        ]
        alternatives = [
            [
                FuriganaSpan(i, i + 1, ch, to_hiragana(piece))
                for i, (ch, piece) in enumerate(zip(run, alt))
            ]
            for alt in solutions[1:]
        ]
        return KanjiRunResult(spans, len(solutions) > 1, alternatives)

    # No valid split at all: keep the whole run as one span. This is the
    # linguistically correct outcome for non-decomposable (jukujikun)
    # readings like 今日 -> きょう, so no flag and no alternatives here —
    # ambiguity means more than one candidate existed, not zero.
    return KanjiRunResult([FuriganaSpan(0, len(run), run, to_hiragana(run_reading))], False, [])


def build_furigana_spans(surface: str, reading_katakana: str) -> FuriganaResult:
    """Align furigana across `surface` given its full reading, splitting on
    kanji vs. non-kanji runs. Returns (spans, needs_review, alternatives) —
    alternatives is a list of alternative full-token span lists, populated
    only when some kanji run within the token had more than one valid
    per-character split.
    """
    if not _KANJI_RE.search(surface):
        return FuriganaResult([{"start": 0, "end": len(surface), "text": surface, "reading": None}], False, [])

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
            literal = to_katakana(surface[start:end])
            pattern_parts.append(re.escape(literal))
    pattern = "^" + "".join(pattern_parts) + "$"

    match = re.match(pattern, reading_katakana)
    if match is None:
        # Reading doesn't literally align with the surface's kana (rare:
        # OOV guesses, unusual symbols like ヶ). Can't place furigana per
        # character; keep it as a single flagged span.
        return FuriganaResult(
            [{"start": 0, "end": len(surface), "text": surface, "reading": to_hiragana(reading_katakana)}],
            True,
            [],
        )

    spans: list[dict] = []
    flagged = False
    ambiguous_range: tuple[int, int, list[list[FuriganaSpan]]] | None = None
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
                {"start": start, "end": end, "text": run, "reading": to_hiragana(run_reading)}
            )
            continue

        sub_spans, sub_flagged, sub_alternatives = _kanji_run_spans(run, run_reading)
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

        # Only the first ambiguous run (left to right) contributes
        # alternatives; a token with more than one independently-ambiguous
        # run is rare enough that cross-producing them isn't worth it here.
        if sub_alternatives and ambiguous_range is None:
            ambiguous_range = (start, end, sub_alternatives)

    alternatives: list[list[dict]] = []
    if ambiguous_range is not None:
        run_start, run_end, sub_alternatives = ambiguous_range
        before = [s for s in spans if s["end"] <= run_start]
        after = [s for s in spans if s["start"] >= run_end]
        for alt_spans in sub_alternatives:
            middle = [
                {"start": run_start + s.start, "end": run_start + s.end, "text": s.text, "reading": s.reading}
                for s in alt_spans
            ]
            alternatives.append(before + middle + after)

    return FuriganaResult(spans, flagged, alternatives)


def slice_spans_by_token(spans: list[dict], token_lengths: list[int]) -> list[Optional[list[dict]]]:
    """Split `spans`, laid over several tokens' surfaces joined in order, into
    a span list per token, starting at 0 for that token. None for a token a
    reading crosses out of, since one reading can't be divided between
    tokens (今日 read きょう)."""
    boundaries = []
    pos = 0
    for length in token_lengths:
        boundaries.append((pos, pos + length))
        pos += length

    result: list[list[dict]] = [[] for _ in token_lengths]
    unattributable: set[int] = set()
    for span in spans:
        covered = [i for i, (b_start, b_end) in enumerate(boundaries) if span["start"] < b_end and span["end"] > b_start]
        if len(covered) == 1:
            i = covered[0]
            b_start, _ = boundaries[i]
            result[i].append(
                {"start": span["start"] - b_start, "end": span["end"] - b_start, "text": span["text"], "reading": span["reading"]}
            )
        elif span["reading"] is None:
            # Plain kana splits at the boundary.
            for i in covered:
                b_start, b_end = boundaries[i]
                lo, hi = max(span["start"], b_start), min(span["end"], b_end)
                result[i].append(
                    {
                        "start": lo - b_start,
                        "end": hi - b_start,
                        "text": span["text"][lo - span["start"] : hi - span["start"]],
                        "reading": None,
                    }
                )
        else:
            unattributable.update(covered)

    return [None if i in unattributable else result[i] for i in range(len(token_lengths))]


def _furigana_spans_for_morpheme(m) -> FuriganaResult:
    """Build furigana spans for one SplitMode.C morpheme, preferring real
    Sudachi word boundaries over per-character guessing whenever `m` can be
    decomposed into them.
    """
    surface = m.surface()
    reading = m.reading_form()

    if len(surface) > 1 and _KANJI_RE.search(surface):
        # Try Sudachi's own SplitMode.A decomposition (see module
        # docstring) before falling back to guesswork: if it splits `m`
        # into independently-recognized words whose readings concatenate
        # back to `m`'s own reading, each piece gets furigana from its own
        # reading — a real word boundary, not an inference.
        sub_morphemes = m.split(sudachi_tokenizer.Tokenizer.SplitMode.A)
        if len(sub_morphemes) >= 2 and "".join(s.reading_form() for s in sub_morphemes) == reading:
            spans: list[dict] = []
            flagged = False
            offset = 0
            for sub in sub_morphemes:
                sub_surface = sub.surface()
                sub_spans, sub_flagged, _sub_alts = build_furigana_spans(sub_surface, sub.reading_form())
                for s in sub_spans:
                    spans.append(
                        {
                            "start": offset + s["start"],
                            "end": offset + s["end"],
                            "text": s["text"],
                            "reading": s["reading"],
                        }
                    )
                flagged = flagged or sub_flagged
                offset += len(sub_surface)
            # No alternatives surfaced here: a picker for a piece's own
            # ambiguity would need that piece's offset into the whole
            # token, which nothing needs yet — no real document has hit a
            # word-boundary split with an independently-ambiguous piece.
            return FuriganaResult(spans, flagged, [])

    # `m` is already irreducible: hand its surface/reading straight to
    # build_furigana_spans, which uses kana anchors to place furigana
    # within it and falls to _kanji_run_spans for any anchor-less run.
    return build_furigana_spans(surface, reading)


@lru_cache(maxsize=4096)
def mixed_reading(word: str) -> str:
    """The reading of `word` in JMDict's convention: kanji rendered in
    hiragana, kana kept exactly as written — including katakana, since
    JMDict's kana_forms mix hiragana and katakana per word (無理ゲー's
    real entry is keyed to むりゲー, not むりげー).
    """
    # Reuses the furigana span alignment: each span's own text is already
    # in whatever script it's written in, so non-kanji spans just pass
    # through unchanged.
    spans, _, _ = build_furigana_spans(word, citation_reading(word))
    return "".join(span["reading"] if span["reading"] is not None else span["text"] for span in spans)


def furigana_spans_for_reading(surface: str, reading_katakana: str) -> list[dict]:
    """Build furigana spans for `surface` given an explicit reading — used
    when a user manually corrects a token's pronunciation (e.g. 三股 as
    さんまた instead of Sudachi's みまた). Doesn't surface alternatives since
    there's nothing left to disambiguate once a human has specified the
    reading directly.
    """
    # Reuses the same alignment machinery as automatic tokenization.
    spans, _, _ = build_furigana_spans(surface, reading_katakana)
    return spans


def a_split_decomposition(word: str) -> list[tuple[str, str, tuple]]:
    """Tokenize `word` standalone with SplitMode.A. Returns a list of
    (surface, reading_katakana, part_of_speech) for each morpheme — used to
    decompose a compound that has no JMDict entry of its own into pieces
    that might (e.g. 勝利の女神 -> 勝利/の/女神, each independently glossable,
    even though the whole phrase isn't a JMDict headword). Empty if `word`
    doesn't decompose (A-split gives a single morpheme back, same as
    C-split already did — nothing further to try)."""
    tok = _get_tokenizer()
    mode_a = sudachi_tokenizer.Tokenizer.SplitMode.A
    morphemes = list(tok.tokenize(word, mode_a))
    if len(morphemes) < 2:
        return []
    return [(m.surface(), m.reading_form(), tuple(m.part_of_speech())) for m in morphemes]


@lru_cache(maxsize=4096)
def heteronym_readings(surface: str, pos: tuple) -> list[str]:
    """Other katakana readings the dictionary lists for this exact surface
    under this exact part-of-speech — a genuine heteronym Sudachi's own
    grammar can't disambiguate (e.g. 今日 -> kyou vs konnichi), as opposed to
    readings that differ because the part-of-speech differs (already
    resolved by Sudachi's own context modeling, e.g. 人 as ひと vs the
    counter-suffix にん)."""
    try:
        candidates = _get_dictionary().lookup(surface)
    except Exception:
        return []
    readings: list[str] = []
    for m in candidates:
        if tuple(m.part_of_speech()) == pos and m.reading_form() not in readings:
            readings.append(m.reading_form())
    return readings


def _reconstruct_citation_reading(reading: str, dict_form_citation: str, alt_reading: str, conjugation_type: str) -> str:
    """Reconstruct the citation-form reading for a heteronym alternative
    that shares the token's own exact conjugation type and form, given
    `conjugation_type` — Sudachi's own paradigm tag for the lexeme
    (`conjugation_type_of(normalized_form)`), e.g. '五段-カ行' or '下一段-バ行'.

    Needed because Sudachi's `dictionary_form()` isn't sense-disambiguated:
    it returns the same citation form for every heteronym sense of a token
    (開く's `dictionary_form()` is identical whether the occurrence means
    あく or ひらく), so `citation_reading(dictionary_form)` alone can't tell
    the alternative readings apart — the transformation has to be derived
    from `reading`/`alt_reading` directly instead.
    """
    if reading == dict_form_citation:
        # This occurrence is already in its own citation-form reading
        # (終止形/連体形) — alt_reading, sharing the same surface and
        # part-of-speech, is shaped the same way and needs no transform.
        return alt_reading

    if conjugation_type.startswith(("上一段", "下一段")):
        # Ichidan citation form is the stem plus る (揃え -> 揃える, アタタメ
        # -> アタタメル): append whatever's missing from this occurrence's
        # own (shorter) reading, which is almost always exactly る.
        return alt_reading + dict_form_citation[len(reading):]

    if conjugation_type.startswith("五段"):
        # Godan citation form's renyou stem replaces the final mora rather
        # than adding one (書く/カク -> 書き/カキ: ク becomes キ, same mora
        # count) — always exactly one mora, since a godan citation ending
        # is always exactly one mora (the row's own -u kana).
        return alt_reading[:-1] + dict_form_citation[-1:]

    # Irregular verbs (サ行変格 する / カ行変格 来る) don't follow either fixed
    # rule — their stem readings vary irregularly across forms — so this
    # leaves alt_reading unchanged rather than guess at a transformation
    # that might not hold.
    return alt_reading


def project_citation_reading(alt_citation_reading: str, reading: str, dict_form_citation: str, conjugation_type: str) -> str:
    """The inverse of _reconstruct_citation_reading: `alt_citation_reading`,
    another katakana reading of a word's citation form, as spelled on an
    occurrence read `reading` (アク -> アイ for 開い). Irregular (サ変/カ変)
    verbs come back unchanged."""
    if reading == dict_form_citation:
        return alt_citation_reading

    if conjugation_type.startswith(("上一段", "下一段")):
        suffix_len = len(dict_form_citation) - len(reading)
        if 0 < suffix_len <= len(alt_citation_reading):
            return alt_citation_reading[: len(alt_citation_reading) - suffix_len]
        return alt_citation_reading

    if conjugation_type.startswith("五段") and alt_citation_reading and reading:
        return alt_citation_reading[:-1] + reading[-1:]

    return alt_citation_reading


def tokenize_document(text: str) -> list[TokenRecord]:
    tok = _get_tokenizer()
    mode_c = sudachi_tokenizer.Tokenizer.SplitMode.C

    records: list[TokenRecord] = []

    for position, m in enumerate(tok.tokenize(text, mode_c)):
        surface = m.surface()
        reading = m.reading_form()
        pos = tuple(m.part_of_speech())
        is_oov = m.is_oov()
        has_kanji = bool(_KANJI_RE.search(surface))

        furigana_spans, span_flag, span_alternatives = _furigana_spans_for_morpheme(m)

        review_reason = None
        conflict_options: list[dict] = []

        if has_kanji and is_oov:
            # No dictionary reading to offer alternatives from at all —
            # this needs a human to type a correction, not pick from a list.
            review_reason = "oov"
        else:
            alt_readings = (
                [r for r in heteronym_readings(surface, pos) if r != reading] if has_kanji else []
            )
            if alt_readings:
                review_reason = "heteronym"
                # heteronym_readings finds alternate readings of the token's
                # inflected SURFACE (温め -> also ヌクメ, ヌルメ), but gloss
                # lookup needs each candidate's CITATION reading (温める ->
                # あたためる/ぬくめる/ぬるめる) — JMDict is keyed by citation
                # form. See _reconstruct_citation_reading for how (it's not
                # a plain suffix append — that only works for ichidan verbs).
                dict_form_citation = citation_reading(m.dictionary_form())
                conjugation_type = conjugation_type_of(m.normalized_form())
                for alt_reading in alt_readings:
                    alt_spans, _, _ = build_furigana_spans(surface, alt_reading)
                    alt_citation = _reconstruct_citation_reading(reading, dict_form_citation, alt_reading, conjugation_type)
                    conflict_options.append(
                        conflict_option_value(to_hiragana(alt_reading), alt_spans, to_hiragana(alt_citation))
                    )
            elif span_flag:
                review_reason = "no_kana_anchor"
                # These alternatives only differ in how the (single, already
                # correct) reading is distributed across kanji — but
                # `reading` is this token's own occurrence reading, which for
                # a conjugated form (出来上がった -> デキアガッ) still carries
                # the inflected tail. JMDict is keyed by the citation form
                # (出来上がる -> できあがる), same as the default option
                # (create_conflicts) already uses — using `reading` directly
                # here would send an inflected, non-citation reading to the
                # gloss lookup the moment a user picks a non-default option
                # on anything but a bare citation-form occurrence.
                citation = mixed_reading(m.normalized_form())
                conflict_options = [
                    conflict_option_value(to_hiragana(reading), alt, citation) for alt in span_alternatives
                ]

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
                conflict_options=conflict_options,
            )
        )

    return records
