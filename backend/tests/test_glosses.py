"""Regression tests for app.glosses.

Pure-function tests (English detection, sense ranking) need no database.
The lookup-routing tests do — they exercise the real JMDict lookup against
the empty test database (see conftest.py), so each lookup is a cache miss
that runs the routing under test rather than returning a cached row. Real
JMDict rather than a mock, because these bugs were specifically about how
real Sudachi/JMDict data interacts.
"""

from sqlalchemy import text

from app.glosses import (
    alternate_reading_options,
    get_or_create_gloss_lookup,
    is_probably_english,
    rank_senses,
    search_jmdict,
    search_readings,
)
from tests.support import jmdict_search


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


class TestRankSenses:
    def _sense(self, pos, gloss):
        return {"pos": [pos], "misc": [], "field": [], "gloss": [gloss]}

    def test_matching_pos_ranks_above_non_matching(self):
        # Mirrors the real で case: a token Sudachi tagged as a particle
        # should surface JMDict's particle-tagged senses first, even though
        # the same surface also has unrelated noun-tagged senses.
        entries = [
            {
                "idseq": 1,
                "kanji_forms": [],
                "senses": [
                    self._sense(
                        "noun (common) (futsuumeishi)", "an unrelated noun sense"
                    ),
                    self._sense("particle", "the particle sense"),
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
                "senses": [
                    self._sense("noun (common) (futsuumeishi)", "uncommon entry")
                ],
            },
            {
                "idseq": 2,
                "kanji_forms": [{"text": "b", "pri": ["ichi1"]}],
                "senses": [self._sense("noun (common) (futsuumeishi)", "common entry")],
            },
        ]
        ranked = rank_senses(entries, "名詞")
        assert ranked[0]["gloss"] == ["common entry"]


class TestSearchReadings:
    def test_finds_a_reading_under_a_different_part_of_speech(self):
        # き (助数詞可能) and ご (一般) are separate entries, so
        # heteronym_readings misses ご.
        assert set(search_readings("期")) == {"キ", "ゴ"}

    def test_common_reading_ranks_first(self):
        # き is JMDict-priority-tagged (news2/nf27), ご isn't.
        assert search_readings("期")[0] == "キ"

    def test_a_word_with_one_reading_has_only_that_one(self):
        assert search_readings("受ける") == ["ウケル"]


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
        pieces = row.entries["pieces"]
        assert [p["surface"] for p in pieces] == ["勝利", "の", "女神"]
        assert any(p["senses"] for p in pieces)

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


class TestSearchJmdict:
    """The sidebar's dictionary search: exact matches first, then entries
    the query begins, ends, or is inside, each of those capped."""

    @staticmethod
    def _tiers(query, entries):
        def tier(entry):
            forms = entry.kanji_forms + entry.kana_forms
            if query in forms:
                return "exact"
            if any(form.startswith(query) for form in forms):
                return "prefix"
            if any(form.endswith(query) for form in forms):
                return "suffix"
            return "substring"

        return [tier(entry) for entry in entries]

    def test_ranks_closer_matches_first_and_caps_the_looser_ones(self):
        # 火 has two entries of its own, read ひ and か.
        assert self._tiers("火", jmdict_search("火")) == [
            *["exact"] * 2,
            *["prefix"] * 3,
            *["suffix"] * 3,
            *["substring"] * 3,
        ]

    def test_exact_matches_are_never_capped(self):
        assert self._tiers("火", jmdict_search("火", max_results_per_tier=1)) == [
            "exact",
            "exact",
            "prefix",
            "suffix",
            "substring",
        ]

    def test_a_blank_query_finds_nothing(self):
        assert search_jmdict("  ") == []
