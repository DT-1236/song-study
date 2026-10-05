"""Tests for app.grammar's predicate groups, against real Sudachi output: the
rule is only as good as Sudachi's tags for real sentences, so a mock would
test nothing."""

import pytest

from app.grammar import find_predicate_groups, grammar_note
from app.tokenization import tokenize_document


def _groups(text: str) -> list[str]:
    records = tokenize_document(text)
    return [
        "".join(records[i].surface for i in group)
        for group in find_predicate_groups(records)
    ]


class TestFindPredicateGroups:
    @pytest.mark.parametrize(
        "text, groups",
        [
            # Contractions are tagged 助動詞, and ん/って are particles.
            ("欲してるんだって", ["欲してるんだって"]),
            ("見ちゃった", ["見ちゃった"]),
            ("書いとくね", ["書いとくね"]),
            ("行かなきゃ", ["行かなきゃ"]),
            # A run of auxiliaries, with ない after たく.
            ("食べさせられたくなかった", ["食べさせられたくなかった"]),
            ("会いたかったんだろう", ["会いたかったんだろう"]),
            ("忘れられないよ", ["忘れられないよ"]),
            ("言わせないで", ["言わせないで"]),
            # Helper verbs after て/で.
            ("読んでみたいんですけど", ["読んでみたいんですけど"]),
            ("泣いてしまいそうだ", ["泣いてしまいそうだ"]),
            ("見て回っている", ["見て回っている"]),
            ("書かれていた", ["書かれていた"]),
            # ちゃ is short for ては.
            ("食べちゃいけない", ["食べちゃいけない"]),
            # A noun directly followed by する.
            ("勉強してた", ["勉強してた"]),
            # 形状詞 and adjectives, with a helper ない after じゃ/は/く.
            ("好きじゃない", ["好きじゃない"]),
            ("静かではない", ["静かではない"]),
            ("美しくない花", ["美しくない"]),
        ],
    )
    def test_groups_a_predicate_with_its_grammar(self, text, groups):
        assert _groups(text) == groups

    @pytest.mark.parametrize(
        "text, groups",
        [
            # いい isn't after て, so it's a predicate of its own.
            ("来てくれたらいいのに", ["来てくれたら", "いいのに"]),
            ("走ってる時に見た夢", ["走ってる", "見た"]),
            # 思う isn't a helper verb.
            ("したいと思う", ["したいと"]),
        ],
    )
    def test_a_new_predicate_starts_a_new_group(self, text, groups):
        assert _groups(text) == groups

    def test_nouns_and_their_particles_are_not_grouped(self):
        assert _groups("君のことが好きだよ") == ["好きだよ"]
        assert _groups("この期に及んで") == ["及んで"]

    def test_a_predicate_with_nothing_attached_is_not_a_group(self):
        assert _groups("走る。") == []

    def test_a_verb_that_can_be_a_helper_is_not_one_without_te(self):
        # 見 is tagged 非自立可能, though it's the main verb.
        assert _groups("彼を見て、驚いた。") == ["見て", "驚いた"]

    def test_members_share_the_heads_position(self):
        records = tokenize_document("猫が寝ている。")
        find_predicate_groups(records)
        assert [(r.surface, r.phrase_start_position) for r in records] == [
            ("猫", None),
            ("が", None),
            ("寝", 2),
            ("て", 2),
            ("いる", 2),
            ("。", None),
        ]


class TestGrammarNote:
    def test_notes_a_known_grammar_word_by_normalized_form(self):
        assert grammar_note("てる", ["助動詞", "*", "*", "*", "*", "*"]).startswith(
            "short for ている"
        )
        # ん as a negative is normalized to ず.
        assert grammar_note("ず", ["助動詞", "*", "*", "*", "*", "*"]).startswith(
            "negation"
        )

    def test_falls_back_by_part_of_speech(self):
        assert (
            grammar_note("かしら", ["助詞", "終助詞", "*", "*", "*", "*"]) == "particle"
        )
        assert (
            grammar_note("未知", ["助動詞", "*", "*", "*", "*", "*"])
            == "grammatical ending"
        )
