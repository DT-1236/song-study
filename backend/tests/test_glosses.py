"""Regression tests for app.glosses.

Pure-function tests (English detection, sense ranking) need no database.
The lookup-routing tests do — they exercise the real JMDict lookup against
the empty test database (see conftest.py), so each lookup is a cache miss
that runs the routing under test rather than returning a cached row. Real
JMDict rather than a mock, because these bugs were specifically about how
real Sudachi/JMDict data interacts.
"""

import json

import pytest
from sqlalchemy import text

from app.glosses import (
    GroupGlossRequest,
    _group_pieces,
    alternate_reading_options,
    get_or_create_gloss_lookup,
    gloss_piece,
    is_probably_english,
    piece_lookups,
    plan_glosses,
    rank_senses,
    search_jmdict,
    search_readings,
    shown_pieces,
)
from app.main import DocumentCreate
from tests.support import create_document, get_document_tokens, jmdict_search


class TestIsProbablyEnglish:
    def test_pure_latin_is_english(self):
        for word in ["gifted", "yeah", "BAD", "the wanted"]:
            assert is_probably_english(word), word

    def test_katakana_loanword_slang_is_not_english(self):
        # Written in Japanese script, even if English-derived — should go
        # through the real JMDict path, not the English stub.
        for word in ["無理ゲー", "ゼッテー", "パッ"]:
            assert not is_probably_english(word), word

    def test_kanji_word_is_not_english(self):
        assert not is_probably_english("花火")


def _sense(pos, gloss):
    return {"pos": [pos], "misc": [], "field": [], "gloss": [gloss]}


def _entries(conn, gloss_id):
    return conn.execute(
        text("SELECT entries FROM gloss_lookups WHERE id = :id"), {"id": gloss_id}
    ).scalar_one()


class TestRankSenses:
    def test_matching_pos_ranks_above_non_matching(self):
        # Mirrors the real で case: a token Sudachi tagged as a particle
        # should surface JMDict's particle-tagged senses first, even though
        # the same surface also has unrelated noun-tagged senses.
        entries = [
            {
                "idseq": 1,
                "kanji_forms": [],
                "senses": [
                    _sense("noun (common) (futsuumeishi)", "an unrelated noun sense"),
                    _sense("particle", "the particle sense"),
                ],
            }
        ]
        ranked = rank_senses(entries, "助詞")
        assert ranked[0]["gloss"] == ["the particle sense"]

    def test_entry_priority_is_the_tiebreaker_when_pos_ties(self):
        entries = [
            {
                "idseq": 1,
                "kanji_forms": [{"text": "a", "pri": []}],
                "senses": [_sense("noun (common) (futsuumeishi)", "uncommon entry")],
            },
            {
                "idseq": 2,
                "kanji_forms": [{"text": "b", "pri": ["ichi1"]}],
                "senses": [_sense("noun (common) (futsuumeishi)", "common entry")],
            },
        ]
        ranked = rank_senses(entries, "名詞")
        assert ranked[0]["gloss"] == ["common entry"]

    def test_a_verb_sense_tagged_only_with_its_class_counts_as_a_verb(self):
        # する's "to do" has no transitivity tag, only "suru verb -
        # included", while its rarer senses are tagged intransitive.
        entries = [
            {
                "idseq": 1,
                "kanji_forms": [],
                "senses": [
                    _sense("suru verb - included", "to do"),
                    _sense("intransitive verb", "to be sensed"),
                ],
            }
        ]
        ranked = rank_senses(entries, "動詞")
        assert ranked[0]["gloss"] == ["to do"]

    @pytest.mark.parametrize(
        "tag, is_verb",
        [
            ("Yodan verb with 'ku' ending (archaic)", True),
            ("verb unspecified", True),
            ("auxiliary verb", False),
            ("adverb (fukushi)", False),
            ("noun or participle which takes the aux. verb suru", False),
        ],
    )
    def test_every_tag_naming_a_verb_counts_as_one(self, tag, is_verb):
        entries = [
            {
                "idseq": 1,
                "kanji_forms": [],
                "senses": [_sense("pronoun", "other"), _sense(tag, "tagged")],
            }
        ]
        ranked = rank_senses(entries, "動詞")
        assert (ranked[0]["gloss"] == ["tagged"]) == is_verb


class TestShownPieces:
    def test_a_piece_is_ranked_and_spelled_when_shown(self):
        # The verb's entry comes second in JMDict's order, so a piece ranked
        # for a verb shows its sense first and is spelled as that entry is.
        entries = [
            {
                "idseq": 1,
                "kanji_forms": [{"text": "甲", "pri": []}],
                "senses": [_sense("noun (common) (futsuumeishi)", "a noun")],
            },
            {
                "idseq": 2,
                "kanji_forms": [{"text": "乙", "pri": []}],
                "senses": [_sense("transitive verb", "to verb")],
            },
        ]
        piece = gloss_piece(
            "こう",
            "こう",
            ("こう", "こう"),
            None,
            ("動詞", "一般", "*", "*", "五段-ワア行", "終止形-一般"),
        )

        # A katakana word's gloss, as _add_katakana_readings stores it.
        composite = {"pieces": [piece], "looked_up_as": "こう"}

        [shown] = shown_pieces(composite, {("こう", "こう"): (entries, "jmdict")})

        assert [sense["gloss"] for sense in shown["senses"]] == [
            ["to verb"],
            ["a noun"],
        ]
        assert shown["surface"] == "乙"

    def test_a_composite_base_flags_no_readings_in_a_group(self):
        # 生物 could also be read なまもの. Its own composite's piece flags
        # that, but in a group its token already shows the reading options.
        piece = gloss_piece(
            "生物",
            "せいぶつ",
            ("生物", "せいぶつ"),
            None,
            ("名詞", "普通名詞", "一般", "*", "*", "*"),
            flags_readings=True,
        )
        lookups = {("生物", "せいぶつ"): ([], "jmdict_miss")}
        request = GroupGlossRequest(
            base_key=("生物x", "せいぶつx"),
            base_alt=None,
            base_part_of_speech=("名詞", "普通名詞", "一般", "*", "*", "*"),
            attached=(),
            reading="せいぶつx",
        )
        found = {request.base_key: ({"pieces": [piece]}, "composite")}

        [own] = shown_pieces({"pieces": [piece]}, lookups)
        [grouped] = shown_pieces({"pieces": _group_pieces(request, found)}, lookups)

        assert own["ambiguous_readings"] == ["なまもの"]
        assert grouped["ambiguous_readings"] == []


class TestSearchReadings:
    def test_finds_a_reading_under_a_different_part_of_speech(self):
        # き (助数詞可能) and ご (一般) are separate entries, so
        # heteronym_readings misses ご.
        assert set(search_readings("期")) == {"キ", "ゴ"}

    def test_common_reading_ranks_first(self):
        # き is JMDict-priority-tagged (news2/nf27), ご isn't.
        assert next(iter(search_readings("期"))) == "キ"

    def test_a_word_with_one_reading_has_only_that_one(self):
        assert search_readings("受ける") == {"ウケル": "下一段"}


class TestAlternateReadingOptions:
    def test_excludes_the_occurrences_own_reading(self):
        options = alternate_reading_options("期", "キ", "期", "期")
        assert [o["reading"] for o in options] == ["ご"]
        assert options[0]["citation_reading"] == "ご"
        assert options[0]["furigana_spans"] == [
            {"start": 0, "end": 1, "text": "期", "reading": "ご"}
        ]

    def test_projects_an_alternate_citation_reading_onto_an_inflected_surface(self):
        # 開い is read ひらい here; JMDict's other reading of 開く, あく, has
        # to come back as it reads on 開い: あい.
        options = alternate_reading_options("開い", "ヒライ", "開く", "開く")
        assert {o["reading"] for o in options} == {"あい"}
        matched = next(o for o in options if o["reading"] == "あい")
        assert matched["citation_reading"] == "あく"

    def test_leaves_out_a_reading_of_another_conjugation_class_on_an_inflected_surface(
        self,
    ):
        # 来る (カ変) is also read きたる, a godan verb: its ending can't be
        # carried over from 来た, so it isn't offered as きたた.
        assert alternate_reading_options("来た", "キタ", "来る", "来る") == []

    def test_still_offers_it_on_the_dictionary_form(self):
        readings = [
            o["reading"]
            for o in alternate_reading_options("来る", "クル", "来る", "来る")
        ]
        assert readings == ["きたる"]

    def test_offers_the_dictionary_forms_reading_when_read_another_way(self):
        # 方 read かた here: its standalone reading, ほう, is another one.
        readings = [
            o["reading"] for o in alternate_reading_options("方", "カタ", "方", "方")
        ]
        assert "ほう" in readings
        assert "かた" not in readings

    def test_empty_for_a_word_with_no_alternate_reading(self):
        assert alternate_reading_options("受け", "ウケ", "受ける", "受ける") == []


class TestGetOrCreateGlossLookup:
    def test_finds_a_real_jmdict_entry(self, db_conn):
        gloss_id = get_or_create_gloss_lookup(db_conn, "花火", "はなび")
        row = db_conn.execute(
            text("SELECT source, entries FROM gloss_lookups WHERE id=:id"),
            {"id": gloss_id},
        ).one()
        assert row.source == "jmdict"
        assert row.entries != []

    def test_caches_identical_lookups(self, db_conn):
        first = get_or_create_gloss_lookup(db_conn, "花火", "はなび")
        second = get_or_create_gloss_lookup(db_conn, "花火", "はなび")
        assert first == second

    def test_composite_fallback_for_an_over_merged_compound(self, db_conn):
        # 勝利の女神 has no JMDict headword of its own, but decomposes via
        # A-split into 勝利/の/女神, each of which does.
        gloss_id = get_or_create_gloss_lookup(db_conn, "勝利の女神", "しょうりのめがみ")
        row = db_conn.execute(
            text("SELECT source, entries FROM gloss_lookups WHERE id=:id"),
            {"id": gloss_id},
        ).one()
        assert row.source == "composite"
        pieces = shown_pieces(row.entries, piece_lookups(db_conn, [row.entries]))
        assert [p["surface"] for p in pieces] == ["勝利", "の", "女神"]
        assert any(p["senses"] for p in pieces)

    def test_a_compound_and_its_own_piece_glossed_together(self, db_conn):
        # 女神 is looked up as a word of its own before 勝利の女神 is split
        # into pieces.
        plan = plan_glosses(
            db_conn,
            [(("勝利の女神", "しょうりのめがみ"), None), (("女神", "めがみ"), None)],
        )
        assert plan.new_rows[("勝利の女神", "しょうりのめがみ")][1] == "composite"

    def test_a_composite_shows_its_pieces_lookups_as_cached_now(self, db_conn):
        gloss_id = get_or_create_gloss_lookup(db_conn, "勝利の女神", "しょうりのめがみ")
        db_conn.execute(
            text(
                """
                UPDATE gloss_lookups SET entries = CAST(:entries AS JSONB)
                WHERE lookup_form = '女神' AND reading = 'めがみ'
                """
            ),
            {
                "entries": json.dumps(
                    [
                        {
                            "idseq": 1,
                            "kanji_forms": [],
                            "senses": [_sense("noun (common) (futsuumeishi)", "new")],
                        }
                    ]
                )
            },
        )

        entries = _entries(db_conn, gloss_id)
        pieces = shown_pieces(entries, piece_lookups(db_conn, [entries]))

        assert [sense["gloss"] for sense in pieces[2]["senses"]] == [["new"]]

    def test_a_composite_looks_up_a_piece_whose_row_is_gone(self, db_conn):
        gloss_id = get_or_create_gloss_lookup(db_conn, "勝利の女神", "しょうりのめがみ")
        db_conn.execute(
            text(
                "DELETE FROM gloss_lookups WHERE lookup_form = '勝利' AND reading = 'しょうり'"
            )
        )

        entries = _entries(db_conn, gloss_id)
        pieces = shown_pieces(entries, piece_lookups(db_conn, [entries]))

        assert pieces[0]["senses"]
        assert (
            db_conn.execute(
                text(
                    "SELECT source FROM gloss_lookups WHERE lookup_form = '勝利' AND reading = 'しょうり'"
                )
            ).scalar_one()
            == "jmdict"
        )

    def test_alt_lookup_form_used_when_primary_spelling_has_no_entry(self, db_conn):
        # normalized_form さり気無い isn't JMDict's registered spelling;
        # dictionary_form さり気ない is. Primary lookup must fail and the
        # alt spelling must be what actually resolves it.
        gloss_id = get_or_create_gloss_lookup(
            db_conn, "さり気無い", "さりげない", alt_lookup_form="さり気ない"
        )
        row = db_conn.execute(
            text("SELECT lookup_form, source, entries FROM gloss_lookups WHERE id=:id"),
            {"id": gloss_id},
        ).one()
        # Cached under the originally-requested spelling, not the alt one.
        assert row.lookup_form == "さり気無い"
        assert row.source == "jmdict"
        assert row.entries != []

    def test_english_word_is_routed_to_the_stub_not_queried_against_jmdict(
        self, db_conn
    ):
        gloss_id = get_or_create_gloss_lookup(db_conn, "gifted", "gifted")
        row = db_conn.execute(
            text("SELECT source, entries FROM gloss_lookups WHERE id=:id"),
            {"id": gloss_id},
        ).one()
        assert row.source == "english_stub"
        assert row.entries == []


# JMDict's entry for する, "to do".
_TO_DO = 1157170


def test_suru_is_glossed_as_to_do(committed_engine):
    # する normalizes to 為る, which read on its own is なる, "to become".
    document_id = create_document(DocumentCreate(title="t", text="そうする。")).id
    [suru] = [t for t in get_document_tokens(document_id) if t.surface == "する"]

    assert (suru.gloss.lookup_form, suru.gloss.reading) == ("為る", "する")
    assert {sense.entry_idseq for sense in suru.gloss.senses} == {_TO_DO}


def _tier(query, entry) -> str:
    """How closely a search result's headword matches `query`."""
    forms = entry.kanji_forms + entry.kana_forms
    if query in forms:
        return "exact"
    if any(form.startswith(query) for form in forms):
        return "prefix"
    if any(form.endswith(query) for form in forms):
        return "suffix"
    return "substring"


class TestSearchJmdict:
    """The sidebar's dictionary search: exact matches first, then entries
    the query begins, ends, or is inside, each of those capped."""

    def test_ranks_closer_matches_first_and_caps_the_looser_ones(self):
        # 柿 has two entries of its own: かき, "persimmon", and こけら, "wood chips".
        assert [_tier("柿", entry) for entry in jmdict_search("柿")] == [
            *["exact"] * 2,
            *["prefix"] * 3,
            *["suffix"] * 3,
            *["substring"] * 3,
        ]

    def test_exact_matches_are_never_capped(self):
        entries = jmdict_search("柿", max_results_per_tier=1)

        assert [_tier("柿", entry) for entry in entries] == [
            *["exact"] * 2,
            "prefix",
            "suffix",
            "substring",
        ]

    def test_a_blank_query_finds_nothing(self):
        assert search_jmdict("  ") == []
