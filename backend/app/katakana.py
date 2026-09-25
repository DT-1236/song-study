"""Looking up Japanese written in katakana for emphasis, as lyrics often do
(ココロノコエ). Sudachi takes a katakana run as one word it can't find, but
looked up as hiragana the same text splits into words JMDict has
(こころ/の/こえ, together the headword こころのこえ).
"""

from __future__ import annotations

import re

from app.glosses import (
    GroupGlossRequest,
    GroupPart,
    citation_key,
    predicate_group_request,
)
from app.grammar import find_predicate_groups
from app.phrase_merge import find_phrase_suggestions
from app.tokenization import to_hiragana, tokenize_document

_KATAKANA_WORD_RE = re.compile(r"^[ァ-ヶー]{2,}$")

_GRAMMAR_POS = frozenset({"助詞", "助動詞", "接尾辞"})


def is_katakana_word(text: str) -> bool:
    """Whether `text` is written entirely in katakana, two characters or more."""
    return bool(_KATAKANA_WORD_RE.match(text))


def hiragana_units(
    katakana: str,
) -> list[GroupGlossRequest | GroupPart] | None:
    """The words of `katakana` looked up as hiragana, in order: a gloss
    request for each word, phrase, or predicate group, and a bare part for
    each grammar word between them. None when the hiragana doesn't split
    into words, as for a loanword (ギガンティック)."""
    records = tokenize_document(to_hiragana(katakana))
    if any(record.is_oov for record in records):
        return None
    find_predicate_groups(records)
    find_phrase_suggestions(records)

    units: list[GroupGlossRequest | GroupPart] = []
    i = 0
    while i < len(records):
        record = records[i]
        suggestion = record.phrase_suggestion
        if suggestion is not None:
            # Taken without review, unlike on the page: there's no other
            # reading of these tokens to lose.
            end = i + suggestion["token_count"]
            attached = records[i + suggestion["phrase_token_count"] : end]
            units.append(
                GroupGlossRequest(
                    base_key=(suggestion["lookup_form"], suggestion["reading"]),
                    base_alt=None,
                    base_part_of_speech=("*",) * 6,
                    attached=tuple(
                        GroupPart.of(r, to_hiragana(r.reading_katakana))
                        for r in attached
                    ),
                    reading=suggestion["surface"],
                )
            )
        elif record.phrase_start_position == record.position:
            end = i + 1
            while (
                end < len(records)
                and records[end].phrase_start_position == record.position
            ):
                end += 1
            members = records[i:end]
            units.append(
                predicate_group_request(
                    members,
                    [to_hiragana(r.reading_katakana) for r in members],
                    citation_key(record.normalized_form, record.dictionary_form),
                )
            )
        elif record.part_of_speech[0] in _GRAMMAR_POS:
            end = i + 1
            units.append(GroupPart.of(record, to_hiragana(record.reading_katakana)))
        else:
            # A one-kana word is a split that didn't find real words: ラブソング
            # read as hiragana ends in ぐ.
            if len(record.surface) == 1:
                return None
            end = i + 1
            units.append(
                predicate_group_request(
                    [record],
                    [to_hiragana(record.reading_katakana)],
                    citation_key(record.normalized_form, record.dictionary_form),
                )
            )
        i = end
    return units
