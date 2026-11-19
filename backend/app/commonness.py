"""How common a word is, by the dictionaries' own frequency data: JMDict's
priority tags for the word, and KANJIDIC2's frequency ranks for its kanji.
New words enroll most common first (see cards.enrollment_order).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import TYPE_CHECKING

from app.glosses import get_raw_conn
from app.tokenization import is_kanji

if TYPE_CHECKING:
    from app.cards import HarvestedWord

# JMDict's "common" tags other than the nf bands. A word with one of these but
# no nf band is still among JMDict's common words: the newspaper count the
# bands come from skips many basic ones (君, する, ずっと).
_COMMON_TAGS = frozenset({"ichi1", "news1", "spec1", "spec2", "gai1"})

# A word marked common but with no nf band, which ranks ahead of every band.
COMMON_UNRANKED_BAND = 0
# A word tagged only news2, ichi2 or gai2.
_LESS_COMMON_BAND = 49
# A word with no tag, or no JMDict entry at all.
UNTAGGED_BAND = 50

# A kanji KANJIDIC2 has but doesn't rank: rarer than the 2,500 it does.
UNRANKED_KANJI = 2501


def _band(tags: set[str]) -> int:
    """The frequency band JMDict's priority `tags` for one entry put a word in,
    lower being more common."""
    nf = [int(tag[2:]) for tag in tags if tag.startswith("nf")]
    if nf:
        return min(nf)
    if tags & _COMMON_TAGS:
        return COMMON_UNRANKED_BAND
    return _LESS_COMMON_BAND if tags else UNTAGGED_BAND


def jmdict_bands(words: Sequence[HarvestedWord]) -> list[int]:
    """The frequency band of each of `words`, in the same order: nf01-nf48's
    number, else COMMON_UNRANKED_BAND, a band past nf48, or UNTAGGED_BAND.
    Lower is more common.

    The tags of both the word's spelling and its reading count, since JMDict
    can tag only one of them (抱きしめる's kana form is nf47, its kanji form
    untagged). With several entries spelled and read alike, the most common
    one counts; with an `idseq`, only that entry does."""
    rows = [
        # f: 0 for the word's own spelling, 1 for its alternate.
        (i, f, form, w.key.reading, w.key.idseq)
        for i, w in enumerate(words)
        for f, form in enumerate((w.key.lookup_form, w.alt_lookup_form))
        if form
    ]
    # The entries each spelling matches, by idseq, with their tags. Matched
    # as gloss lookup (glosses._lookup_entries) matches them: an entry
    # written or read as the spelling, with a kana form that is the reading
    # and isn't restricted to other spellings.
    matched: dict[tuple[int, int], dict[int, set[str]]] = {}
    for i, f, idseq, tag in get_raw_conn().execute(
        """
        WITH w AS (
            SELECT json_extract(value, '$[0]') AS i,
                   json_extract(value, '$[1]') AS f,
                   json_extract(value, '$[2]') AS form,
                   json_extract(value, '$[3]') AS reading,
                   json_extract(value, '$[4]') AS idseq
            FROM json_each(?)
        ),
        m AS (
            SELECT w.i, w.f, kn.idseq, kn.ID AS kana_id, kj.ID AS kanji_id
            FROM w
            JOIN Kana kn ON kn.text = w.reading
             AND (w.idseq IS NULL OR kn.idseq = w.idseq)
            LEFT JOIN Kanji kj ON kj.idseq = kn.idseq AND kj.text = w.form
            WHERE (
                kj.ID IS NOT NULL OR EXISTS (
                    SELECT 1 FROM Kana k WHERE k.idseq = kn.idseq AND k.text = w.form
                )
            ) AND (
                NOT EXISTS (SELECT 1 FROM KNR r WHERE r.kid = kn.ID)
                OR EXISTS (SELECT 1 FROM KNR r WHERE r.kid = kn.ID AND r.text = w.form)
            )
        )
        -- A LEFT JOIN, so an untagged entry still counts as matched.
        SELECT m.i, m.f, m.idseq, p.text FROM m LEFT JOIN KNP p ON p.kid = m.kana_id
        UNION ALL
        SELECT m.i, m.f, m.idseq, p.text FROM m JOIN KJP p ON p.kid = m.kanji_id
        """,
        (json.dumps(rows),),
    ):
        tags = matched.setdefault((i, f), {}).setdefault(idseq, set())
        if tag:
            tags.add(tag)
    return [
        min(
            # The alternate spelling only when the word's own matches
            # nothing, as gloss lookup (glosses._lookup) tries them.
            map(_band, (matched.get((i, 0)) or matched.get((i, 1)) or {}).values()),
            default=UNTAGGED_BAND,
        )
        for i in range(len(words))
    ]


def rarest_kanji_ranks(forms: Sequence[str]) -> list[int]:
    """For each of `forms`, in the same order, the KANJIDIC2 frequency rank of
    its least used kanji (UNRANKED_KANJI for one KANJIDIC2 doesn't rank), or 0
    if it has none. A character KANJIDIC2 has no entry for, which is the
    repeat mark 々, doesn't count."""
    literals = sorted({ch for form in forms for ch in form if is_kanji(ch)})
    ranks = {
        literal: int(freq) if freq else UNRANKED_KANJI
        for literal, freq in get_raw_conn().execute(
            # KANJIDIC2 stores freq as text.
            "SELECT literal, freq FROM character WHERE literal IN "
            f"({','.join('?' * len(literals))})",
            literals,
        )
    }
    return [max((ranks[ch] for ch in form if ch in ranks), default=0) for form in forms]
