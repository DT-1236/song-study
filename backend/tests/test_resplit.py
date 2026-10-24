"""Tests for app.resplit, against real Sudachi output: the boundaries it
repairs are ones Sudachi's own dictionary leads it to get wrong, so a mock
would test nothing."""

import pytest

from app.tokenization import tokenize_document


def _split(text):
    return [(r.surface, r.part_of_speech[0]) for r in tokenize_document(text)]


class TestClassicalAdjectiveBoundary:
    def test_moves_the_ending_off_the_following_noun(self):
        # き線 is a dictionary word of its own (饋線), so Sudachi splits
        # 青き線 ("blue line") after 青.
        assert _split("赤と青き線") == [
            ("赤", "名詞"),
            ("と", "助詞"),
            ("青き", "形容詞"),
            ("線", "名詞"),
        ]

    def test_repaired_tokens_keep_their_place_in_the_text(self):
        text = "青き線を引く"
        assert [
            (r.surface, r.char_begin, r.char_end) for r in tokenize_document(text)
        ] == [
            ("青き", 0, 2),
            ("線", 2, 3),
            ("を", 3, 4),
            ("引く", 4, 6),
        ]
        assert all(
            text[r.char_begin : r.char_end] == r.surface
            for r in tokenize_document(text)
        )

    def test_the_adjective_is_glossed_as_its_modern_form(self):
        [adjective] = [
            r for r in tokenize_document("赤と青き線") if r.surface == "青き"
        ]
        assert adjective.normalized_form == "青い"

    @pytest.mark.parametrize(
        "text, split",
        [
            # Sudachi already gets these right.
            ("遠き道のり", [("遠き", "形容詞"), ("道のり", "名詞")]),
            (
                "古き良き時代",
                [("古き", "形容詞"), ("良き", "形容詞"), ("時代", "名詞")],
            ),
            ("青く光る線", [("青く", "形容詞"), ("光る", "動詞"), ("線", "名詞")]),
            # と+き is 時, not an adjective, so the boundary stays.
            ("月と星空", [("月", "名詞"), ("と", "助詞"), ("星空", "名詞")]),
            (
                "この線は赤い",
                [
                    ("この", "連体詞"),
                    ("線", "名詞"),
                    ("は", "助詞"),
                    ("赤い", "形容詞"),
                ],
            ),
            # 行きし is no adjective either.
            ("行きし方", [("行き", "動詞"), ("し", "動詞"), ("方", "接尾辞")]),
            (
                "好き嫌いはない",
                [("好き嫌い", "名詞"), ("は", "助詞"), ("ない", "形容詞")],
            ),
            # 美き is no single morpheme (Sudachi reads it 美 + き), so
            # there is no classical adjective to move the ending onto.
            ("美き線", [("美", "名詞"), ("き線", "名詞")]),
            # 青し is a classical adjective, but the しょー that follows it
            # would be left as ょー, which Sudachi has no entry for.
            ("青しょー", [("青", "名詞"), ("しょー", "名詞")]),
        ],
    )
    def test_leaves_other_boundaries_alone(self, text, split):
        assert _split(text) == split

    @pytest.mark.parametrize(
        "text, word", [("赤きつね", "きつね"), ("青きのこ", "きのこ")]
    )
    def test_keeps_a_word_that_has_its_own_entry_whole(self, text, word):
        # 赤き + つね would be a worse reading than 赤 + きつね ("fox"), and
        # JMDict having きつね is what tells them apart.
        assert _split(text) == [(text[0], "名詞"), (word, "名詞")]
