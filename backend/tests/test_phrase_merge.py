"""Tests for app.phrase_merge, against real Sudachi + JMDict (no DB): the
cases are about how real tokenizer output meets real dictionary data, so a
mock would test nothing.

この期に及んで is the motivating idiom: Sudachi splits it into five tokens and
reads its 期 as き, where the idiom has ご. 今日は -> こんにちは and し+たく ->
したく are coincidental matches, which is why phrases are only suggested.
"""

from app.glosses import gloss_key
from app.grammar import find_predicate_groups
from app.phrase_merge import _can_start_phrase, find_phrase_suggestions
from app.tokenization import tokenize_document


def _records(text):
    # In the same order as document processing.
    records = tokenize_document(text)
    find_predicate_groups(records)
    find_phrase_suggestions(records)
    return records


def _suggestions(text):
    return {r.position: r.phrase_suggestion for r in _records(text) if r.phrase_suggestion is not None}


class TestFindPhraseSuggestions:
    def test_finds_the_motivating_idiom_with_its_jmdict_reading(self):
        assert _suggestions("この期に及んでまだ言い訳をするのか")[0] == {
            "surface": "この期に及んで",
            "lookup_form": "この期に及んで",
            "reading": "このごにおよんで",
            "token_count": 5,
            "phrase_token_count": 5,
        }

    def test_a_coincidental_match_is_only_suggested(self):
        # 今日 + は spells こんにちは ("hello"), but 今日 is still glossed as
        # きょう.
        records = _records("今日は雨です。")
        assert records[0].phrase_suggestion == {
            "surface": "今日は",
            "lookup_form": "今日は",
            "reading": "こんにちは",
            "token_count": 2,
            "phrase_token_count": 2,
        }
        assert gloss_key(records[0]) == ("今日", "きょう")

    def test_extends_through_auxiliaries_to_reach_an_idiom(self):
        assert _suggestions("お願いします")[0] == {
            "surface": "お願いします",
            "lookup_form": "お願いします",
            "reading": "おねがいします",
            "token_count": 4,
            "phrase_token_count": 4,
        }

    def test_a_match_through_an_inflected_verbs_dictionary_form_takes_its_grammar_along(self):
        # 真に受け is only a headword as 真に受ける, and the てみて after it
        # belongs to 受け.
        assert _suggestions("真に受けてみて") == {
            0: {
                "surface": "真に受けてみて",
                "lookup_form": "真に受ける",
                "reading": "まにうける",
                "token_count": 6,
                "phrase_token_count": 3,
            }
        }

    def test_a_match_within_a_predicate_group_is_not_suggested(self):
        # し + たく spells したく ("preparations"), and して and しまった are
        # headwords too, but each is only its group's own verb and grammar.
        assert _suggestions("後悔だけはしたくない") == {}
        assert _suggestions("彼女に恋してしまった。") == {}

    def test_a_match_starting_before_a_group_can_cover_it(self):
        # 火をつけたり starts at the noun 火, before the group つけたり, which
        # is a headword on its own too.
        surfaces = {s["surface"] for s in _suggestions("人を殺したり家に火をつけたり").values()}
        assert "火をつけたり" in surfaces
        assert "つけたり" not in surfaces

    def test_no_suggestions_for_ordinary_tokens(self):
        assert _suggestions("猫が窓の外を見ている。") == {}

    def test_finds_a_headword_split_across_tokens(self):
        assert _suggestions("御釈迦様が仰いました。")[0]["surface"] == "御釈迦様"

    def test_a_dictionary_form_completion_still_has_to_be_a_headword(self):
        # 歩い + its dictionary form 歩く completes nothing here.
        suggestions = _suggestions("彼は静かに歩いた。")
        assert not any(s["surface"].startswith("歩") for s in suggestions.values())

    def test_does_not_start_a_scan_from_a_particle_or_punctuation(self):
        assert not _can_start_phrase(["助詞", "*", "*", "*", "*", "*"])
        assert not _can_start_phrase(["補助記号", "*", "*", "*", "*", "*"])
        assert _can_start_phrase(["名詞", "*", "*", "*", "*", "*"])
