"""Regression tests for app.glosses.

Pure-function tests (English detection, sense ranking) need no database.
The lookup-routing tests do — they exercise the real JMDict lookup (via a
throwaway document/token inside a rolled-back transaction, see conftest.py),
because these bugs were specifically about how real Sudachi/JMDict data
interacts, not something a mock would have caught.
"""

from sqlalchemy import text

from app.glosses import _is_probably_english, get_or_create_gloss_lookup, rank_senses


class TestIsProbablyEnglish:
    def test_pure_latin_is_english(self):
        for word in ["gifted", "yeah", "BAD", "the wanted"]:
            assert _is_probably_english(word), word

    def test_katakana_loanword_slang_is_not_english(self):
        # Written in Japanese script, even if English-derived — should go
        # through the real JMDict path, not the English stub.
        for word in ["無理ゲー", "ゼッテー", "パッ"]:
            assert not _is_probably_english(word), word

    def test_kanji_word_is_not_english(self):
        assert not _is_probably_english("花火")


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
                    self._sense("noun (common) (futsuumeishi)", "an unrelated noun sense"),
                    self._sense("particle", "the particle sense"),
                ],
            }
        ]
        ranked = rank_senses(entries, "助詞")
        assert ranked[0]["gloss"] == ["the particle sense"]

    def test_entry_priority_is_the_tiebreaker_when_pos_ties(self):
        entries = [
            {"idseq": 1, "kanji_forms": [{"text": "a", "pri": []}], "senses": [self._sense("noun (common) (futsuumeishi)", "uncommon entry")]},
            {"idseq": 2, "kanji_forms": [{"text": "b", "pri": ["ichi1"]}], "senses": [self._sense("noun (common) (futsuumeishi)", "common entry")]},
        ]
        ranked = rank_senses(entries, "名詞")
        assert ranked[0]["gloss"] == ["common entry"]


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

    def test_english_word_is_routed_to_the_stub_not_queried_against_jmdict(self, db_conn):
        gloss_id = get_or_create_gloss_lookup(db_conn, "gifted", "gifted")
        row = db_conn.execute(
            text("SELECT source, entries FROM gloss_lookups WHERE id=:id"),
            {"id": gloss_id},
        ).one()
        assert row.source == "english_stub"
        assert row.entries == []
