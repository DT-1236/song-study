"""Tests for glossing katakana-written Japanese by looking it up as hiragana
(app/katakana.py), against real Sudachi and JMDict data."""

from __future__ import annotations

from sqlalchemy import text

from app.glosses import (
    GroupGlossRequest,
    GroupPart,
    get_or_create_gloss_lookup,
    piece_lookups,
    shown_pieces,
)
from app.katakana import hiragana_units, is_katakana_word
from app.main import (
    DocumentCreate,
)
from tests.support import create_document, get_document_tokens


def _gloss(conn, gloss_id):
    return conn.execute(
        text("SELECT entries, source FROM gloss_lookups WHERE id = :id"),
        {"id": gloss_id},
    ).one()


def _shown(conn, gloss) -> list[dict]:
    """The pieces of `gloss`, a composite gloss row, as shown."""
    return shown_pieces(gloss.entries, piece_lookups(conn, [gloss.entries]))


class TestHiraganaUnits:
    def test_fuses_a_phrase_with_its_own_entry(self):
        # こころ/の/こえ, together the headword こころのこえ.
        [(unit, spans)] = hiragana_units("ココロノコエ")
        assert unit.base_key == ("こころのこえ", "こころのこえ")
        assert spans == [(0, 6)]

    def test_groups_a_predicate_with_its_grammar(self):
        [(unit, spans)] = hiragana_units("アイタイ")
        assert unit.base_key == ("あう", "あう")
        assert [part.dictionary_form for part in unit.attached] == ["たい"]
        # アイ, then タイ.
        assert spans == [(0, 2), (2, 4)]

    def test_keeps_grammar_words_between_words(self):
        units = hiragana_units("キミトボクノミライ")
        assert [type(unit) for unit, _ in units] == [
            GroupGlossRequest,
            GroupPart,
            GroupGlossRequest,
            GroupPart,
            GroupGlossRequest,
        ]
        assert units[4][0].base_key == ("未来", "みらい")
        assert [spans for _, spans in units] == [
            [(0, 2)],
            [(2, 3)],
            [(3, 5)],
            [(5, 6)],
            [(6, 9)],
        ]

    def test_rejects_a_loanword_that_does_not_split_into_words(self):
        assert hiragana_units("ギガンティック") is None
        assert hiragana_units("フォーエバー") is None
        # らぶ/そん/ぐ ends in a one-kana word.
        assert hiragana_units("ラブソング") is None

    def test_is_katakana_word(self):
        assert is_katakana_word("ココロノコエ")
        assert is_katakana_word("ラブー")
        assert not is_katakana_word("ア")
        assert not is_katakana_word("ココロの")


class TestKatakanaGlosses:
    def test_katakana_without_an_entry_is_glossed_as_hiragana(self, db_conn):
        gloss = _gloss(
            db_conn, get_or_create_gloss_lookup(db_conn, "ココロノコエ", "ココロノコエ")
        )

        assert gloss.source == "composite"
        assert gloss.entries["looked_up_as"] == "こころのこえ"
        [piece] = _shown(db_conn, gloss)
        # Written as the entry usually is, not as the katakana reads it out.
        assert (piece["surface"], piece["reading"]) == ("心の声", "こころのこえ")
        assert "voice of one's heart" in piece["senses"][0]["gloss"]

    def test_grammar_words_get_notes(self, db_conn):
        gloss = _gloss(
            db_conn,
            get_or_create_gloss_lookup(
                db_conn, "キミトボクノミライ", "キミトボクノミライ"
            ),
        )

        assert [
            (p["surface"], p["note"] is not None) for p in _shown(db_conn, gloss)
        ] == [
            ("君", False),
            ("と", True),
            ("僕", False),
            ("の", True),
            ("未来", False),
        ]

    def test_a_words_kanji_follows_the_sense_shown_first(self, db_conn):
        # あう is 会う, 合う, or 遭う; 会う is the entry the first sense comes
        # from. ナイテル's なく is 泣く rather than 鳴く the same way.
        gloss = _gloss(
            db_conn, get_or_create_gloss_lookup(db_conn, "アイタイ", "アイタイ")
        )
        assert [p["surface"] for p in _shown(db_conn, gloss)] == [
            "会う",
            "たい",
        ]

        gloss = _gloss(
            db_conn, get_or_create_gloss_lookup(db_conn, "ナイテル", "ナイテル")
        )
        assert _shown(db_conn, gloss)[0]["surface"] == "泣く"

    def test_each_piece_knows_where_it_is_and_which_word_it_belongs_to(self, db_conn):
        gloss = _gloss(
            db_conn,
            get_or_create_gloss_lookup(db_conn, "ボクノアイタイ", "ボクノアイタイ"),
        )

        assert [
            (p["surface"], p["span"], p["unit"]) for p in gloss.entries["pieces"]
        ] == [
            ("僕", [0, 2], 0),
            ("の", [2, 3], 1),
            ("あう", [3, 5], 2),
            ("たい", [5, 7], 2),
        ]

    def test_katakana_with_its_own_entry_is_unchanged(self, db_conn):
        gloss = _gloss(db_conn, get_or_create_gloss_lookup(db_conn, "テレビ", "テレビ"))
        assert gloss.source == "jmdict" and gloss.entries

    def test_a_loanword_without_an_entry_stays_empty(self, db_conn):
        gloss = _gloss(
            db_conn,
            get_or_create_gloss_lookup(db_conn, "ギガンティック", "ギガンティック"),
        )
        assert (gloss.entries, gloss.source) == ([], "jmdict_miss")


def test_a_document_shows_katakana_glossed_as_hiragana(committed_engine):
    document_id = create_document(
        DocumentCreate(title="t", text="ココロノコエが聞こえる。")
    ).id

    token = get_document_tokens(document_id)[0]

    assert token.surface == "ココロノコエ"
    assert token.gloss.looked_up_as == "こころのこえ"
    assert token.gloss.pieces[0].senses
