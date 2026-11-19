"""How common a word is, by the dictionaries' own frequency data: JMDict's
priority tags for the word, and KANJIDIC2's frequency ranks for its kanji.
New words enroll most common first (see cards.enrollment_order).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence

from app.glosses import get_raw_conn, kanjidic_rows
from app.tokenization import is_kanji

# JMDict's "common" tags other than the nf bands. A word with one of these but
# no nf band is still among JMDict's common words: the newspaper count the
# bands come from skips many basic ones (君, する, ずっと).
_COMMON_TAGS = frozenset({"ichi1", "news1", "spec1", "spec2", "gai1"})

# The band of a word marked common with no nf band, which ranks ahead of every
# band; of one tagged only news2, ichi2 or gai2; and of one with no tag, or no
# JMDict entry at all.
COMMON_UNRANKED_BAND = 0
LESS_COMMON_BAND = 49
UNTAGGED_BAND = 50

# KANJIDIC2 ranks the 2,500 most used kanji; one it has but doesn't rank is
# rarer than all of those.
UNRANKED_KANJI = 2501


def _band(tags: Iterable[str]) -> int:
    """The frequency band JMDict's priority `tags` for one entry put a word in,
    lower being more common."""
    tags = set(tags)
    nf = [int(tag[2:]) for tag in tags if tag.startswith("nf")]
    if nf:
        return min(nf)
    if tags & _COMMON_TAGS:
        return COMMON_UNRANKED_BAND
    return LESS_COMMON_BAND if tags else UNTAGGED_BAND


def jmdict_bands(
    words: Sequence[tuple[str, str | None, str, int | None]],
) -> list[int]:
    """The frequency band of each of `words`, a (lookup_form, alt_lookup_form,
    reading, idseq) each, in the same order: nf01-nf48's number, else
    COMMON_UNRANKED_BAND, LESS_COMMON_BAND or UNTAGGED_BAND. Lower is more
    common.

    The tags of both the word's spelling and its reading count, since JMDict
    can tag only one of them (抱きしめる's kana form is nf47, its kanji form
    untagged). With several entries spelled and read alike, the most common
    one counts; with an `idseq`, only that entry does."""
    rows = [
        # A spelling without kanji (ずっと, or a word sung in katakana) is
        # matched on its reading alone.
        (i, form, reading, idseq, not any(is_kanji(ch) for ch in form))
        for i, (lookup_form, alt, reading, idseq) in enumerate(words)
        for form in dict.fromkeys(f for f in (lookup_form, alt) if f)
    ]
    tags: dict[tuple[int, int], set[str]] = {}
    for i, idseq, tag in get_raw_conn().execute(
        """
        WITH w AS (
            SELECT json_extract(value, '$[0]') AS i,
                   json_extract(value, '$[1]') AS form,
                   json_extract(value, '$[2]') AS reading,
                   json_extract(value, '$[3]') AS idseq,
                   json_extract(value, '$[4]') AS kana_only
            FROM json_each(?)
        )
        SELECT w.i, kn.idseq, p.text FROM w
        JOIN Kana kn ON kn.text = w.reading
         AND (w.idseq IS NULL OR kn.idseq = w.idseq)
        JOIN KNP p ON p.kid = kn.ID
        WHERE w.kana_only OR EXISTS (
            SELECT 1 FROM Kanji kj WHERE kj.idseq = kn.idseq AND kj.text = w.form
        )
        UNION ALL
        SELECT w.i, kj.idseq, p.text FROM w
        JOIN Kanji kj ON kj.text = w.form
         AND (w.idseq IS NULL OR kj.idseq = w.idseq)
        JOIN KJP p ON p.kid = kj.ID
        WHERE EXISTS (
            SELECT 1 FROM Kana kn WHERE kn.idseq = kj.idseq AND kn.text = w.reading
        )
        """,
        (json.dumps(rows),),
    ):
        tags.setdefault((i, idseq), set()).add(tag)
    bands = [UNTAGGED_BAND] * len(words)
    for (i, _), entry_tags in tags.items():
        bands[i] = min(bands[i], _band(entry_tags))
    return bands


def rarest_kanji_ranks(forms: Sequence[str]) -> list[int]:
    """For each of `forms`, in the same order, the KANJIDIC2 frequency rank of
    its least used kanji (UNRANKED_KANJI for one KANJIDIC2 doesn't rank), or 0
    if it has none. A character KANJIDIC2 has no entry for, which is the
    repeat mark 々, doesn't count."""
    rows = kanjidic_rows({ch for form in forms for ch in form if is_kanji(ch)})
    ranks = {
        literal: int(row.freq) if row.freq else UNRANKED_KANJI
        for literal, row in rows.items()
    }
    return [max((ranks[ch] for ch in form if ch in ranks), default=0) for form in forms]
