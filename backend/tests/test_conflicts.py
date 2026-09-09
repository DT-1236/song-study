"""Regression tests for app.conflicts.

All DB-integration (via db_conn/make_token, see conftest.py) — every case
here reproduces a real bug found this session:

- resolve_conflict originally only updated furigana_override on a switch,
  leaving a stale gloss paired with the newly-selected reading.
- attach_glosses used to clobber a user's correct_reading correction on a
  later gap-fill pass (fixed elsewhere, in glosses.py, but correct_reading's
  own "preserve the original as an unselected row" behavior is what makes
  redo possible at all, so it's covered here).
- Concurrent resolve/correct calls for the same token raced past the
  "one selected row per token" unique index before the FOR UPDATE locks
  were added; that's a concurrency property, not something a single-threaded
  test can usefully assert, so it's not re-tested here.
"""

from __future__ import annotations

import json

from sqlalchemy import text

from app.conflicts import (
    ConflictNotFound,
    TokenNotFound,
    correct_reading,
    create_conflicts,
    resolve_conflict,
)
from app.tokenization import TokenRecord
from tests.conftest import make_token


def _conflicts_for(conn, token_id):
    return conn.execute(
        text(
            """
            SELECT id, kind, value, selected
            FROM conflicts
            WHERE token_id = :token_id
            ORDER BY id
            """
        ),
        {"token_id": token_id},
    ).all()


def _token_row(conn, token_id):
    return conn.execute(
        text(
            "SELECT gloss_lookup_id, furigana_override, needs_review FROM tokens WHERE id = :id"
        ),
        {"id": token_id},
    ).one()


class TestCreateConflicts:
    def test_no_rows_for_records_with_no_conflict_options(self, db_conn):
        document_id = db_conn.execute(
            text("INSERT INTO documents (title, text) VALUES ('t', 't') RETURNING id")
        ).scalar_one()
        token_id = make_token(db_conn, document_id=document_id, position=0)

        record = TokenRecord(
            position=0,
            char_begin=0,
            char_end=1,
            surface="test",
            dictionary_form="test",
            normalized_form="test",
            reading_katakana="テスト",
            part_of_speech=["名詞", "普通名詞", "一般", "*", "*", "*"],
            is_oov=False,
            furigana_spans=[],
            needs_review=False,
            review_reason=None,
            conflict_options=[],
        )
        create_conflicts(db_conn, document_id, [record])

        assert _conflicts_for(db_conn, token_id) == []

    def test_flagged_record_gets_a_selected_default_plus_unselected_alternatives(self, db_conn):
        document_id = db_conn.execute(
            text("INSERT INTO documents (title, text) VALUES ('t', 't') RETURNING id")
        ).scalar_one()
        token_id = make_token(db_conn, document_id=document_id, position=0, surface="今日")

        alt_option = {
            "reading": "こんにち",
            "furigana_spans": [{"start": 0, "end": 2, "text": "今日", "reading": "こんにち"}],
            "citation_reading": "こんにち",
        }
        record = TokenRecord(
            position=0,
            char_begin=0,
            char_end=2,
            surface="今日",
            dictionary_form="今日",
            normalized_form="今日",
            reading_katakana="キョウ",
            part_of_speech=["名詞", "普通名詞", "副詞可能", "*", "*", "*"],
            is_oov=False,
            furigana_spans=[{"start": 0, "end": 2, "text": "今日", "reading": "きょう"}],
            needs_review=True,
            review_reason="heteronym",
            conflict_options=[alt_option],
        )
        create_conflicts(db_conn, document_id, [record])

        rows = _conflicts_for(db_conn, token_id)
        assert len(rows) == 2
        assert sum(r.selected for r in rows) == 1

        selected = next(r for r in rows if r.selected)
        alt = next(r for r in rows if not r.selected)
        assert selected.kind == "heteronym"
        assert selected.value["reading"] == "きょう"
        assert selected.value["citation_reading"] == "きょう"
        assert alt.value["reading"] == "こんにち"


class TestResolveConflict:
    def _seed_heteronym_token(self, conn):
        document_id = conn.execute(
            text("INSERT INTO documents (title, text) VALUES ('t', 't') RETURNING id")
        ).scalar_one()
        token_id = make_token(
            conn,
            document_id=document_id,
            surface="今日",
            dictionary_form="今日",
            normalized_form="今日",
            reading_katakana="キョウ",
        )
        default_value = {
            "reading": "きょう",
            "furigana_spans": [{"start": 0, "end": 2, "text": "今日", "reading": "きょう"}],
            "citation_reading": "きょう",
        }
        alt_value = {
            "reading": "こんにち",
            "furigana_spans": [{"start": 0, "end": 2, "text": "今日", "reading": "こんにち"}],
            "citation_reading": "こんにち",
        }
        default_id = conn.execute(
            text(
                """
                INSERT INTO conflicts (token_id, kind, value, selected, selected_at)
                VALUES (:token_id, 'heteronym', CAST(:value AS JSONB), TRUE, now())
                RETURNING id
                """
            ),
            {"token_id": token_id, "value": json.dumps(default_value)},
        ).scalar_one()
        alt_id = conn.execute(
            text(
                """
                INSERT INTO conflicts (token_id, kind, value, selected)
                VALUES (:token_id, 'heteronym', CAST(:value AS JSONB), FALSE)
                RETURNING id
                """
            ),
            {"token_id": token_id, "value": json.dumps(alt_value)},
        ).scalar_one()
        return document_id, token_id, default_id, alt_id

    def test_switching_moves_selected_and_updates_furigana(self, db_conn):
        document_id, token_id, default_id, alt_id = self._seed_heteronym_token(db_conn)

        resolve_conflict(db_conn, document_id, token_id, alt_id)

        rows = _conflicts_for(db_conn, token_id)
        assert {r.id: r.selected for r in rows} == {default_id: False, alt_id: True}

        token = _token_row(db_conn, token_id)
        assert token.needs_review is False
        assert token.furigana_override[0]["reading"] == "こんにち"

    def test_switching_re_resolves_the_gloss_not_just_furigana(self, db_conn):
        # The regression: resolve_conflict used to only touch
        # furigana_override, so gloss_lookup_id stayed pinned to whichever
        # reading was selected first — switching between two readings that
        # are genuinely different JMDict entries must produce two different
        # gloss_lookup_id values.
        document_id, token_id, default_id, alt_id = self._seed_heteronym_token(db_conn)

        resolve_conflict(db_conn, document_id, token_id, default_id)
        gloss_for_default = _token_row(db_conn, token_id).gloss_lookup_id

        resolve_conflict(db_conn, document_id, token_id, alt_id)
        gloss_for_alt = _token_row(db_conn, token_id).gloss_lookup_id

        assert gloss_for_default is not None
        assert gloss_for_alt is not None
        assert gloss_for_default != gloss_for_alt

    def test_raises_when_conflict_does_not_belong_to_token(self, db_conn):
        document_id, token_id, default_id, alt_id = self._seed_heteronym_token(db_conn)
        other_token_id = make_token(db_conn, document_id=document_id, position=1)

        try:
            resolve_conflict(db_conn, document_id, other_token_id, default_id)
            assert False, "expected ConflictNotFound"
        except ConflictNotFound:
            pass


class TestCorrectReading:
    def _seed_uncorrected_token(self, conn):
        document_id = conn.execute(
            text("INSERT INTO documents (title, text) VALUES ('t', 't') RETURNING id")
        ).scalar_one()
        token_id = make_token(
            conn,
            document_id=document_id,
            surface="三股",
            dictionary_form="三股",
            normalized_form="三股",
            reading_katakana="ミマタ",
            char_end=2,
            furigana_spans=[{"start": 0, "end": 2, "text": "三股", "reading": "みまた"}],
        )
        return document_id, token_id

    def test_first_correction_preserves_sudachis_original_as_an_unselected_row(self, db_conn):
        document_id, token_id = self._seed_uncorrected_token(db_conn)

        correct_reading(db_conn, document_id, token_id, "さんまた")

        rows = _conflicts_for(db_conn, token_id)
        assert len(rows) == 2
        selected = next(r for r in rows if r.selected)
        original = next(r for r in rows if not r.selected)
        assert selected.value["reading"] == "さんまた"
        assert selected.kind == "custom"
        assert original.value["reading"] == "みまた"

        token = _token_row(db_conn, token_id)
        assert token.needs_review is False
        # 三股 is a 2-kanji run, so the override is split per-character
        # (さん/また), not one whole-word span.
        assert "".join(s["reading"] or "" for s in token.furigana_override) == "さんまた"

    def test_second_correction_does_not_duplicate_the_preserved_original(self, db_conn):
        document_id, token_id = self._seed_uncorrected_token(db_conn)

        correct_reading(db_conn, document_id, token_id, "さんまた")
        correct_reading(db_conn, document_id, token_id, "みつまた")

        rows = _conflicts_for(db_conn, token_id)
        # original (unselected) + first correction (now unselected) + second
        # correction (selected) - never a second copy of the original.
        assert len(rows) == 3
        readings = sorted(r.value["reading"] for r in rows)
        assert readings == sorted(["みまた", "さんまた", "みつまた"])
        assert sum(r.selected for r in rows) == 1
        assert next(r for r in rows if r.selected).value["reading"] == "みつまた"

    def test_can_redo_back_to_the_preserved_original_via_resolve_conflict(self, db_conn):
        document_id, token_id = self._seed_uncorrected_token(db_conn)

        correct_reading(db_conn, document_id, token_id, "さんまた")
        rows = _conflicts_for(db_conn, token_id)
        original_row = next(r for r in rows if r.value["reading"] == "みまた")

        resolve_conflict(db_conn, document_id, token_id, original_row.id)

        token = _token_row(db_conn, token_id)
        assert "".join(s["reading"] or "" for s in token.furigana_override) == "みまた"
        rows = _conflicts_for(db_conn, token_id)
        assert next(r for r in rows if r.selected).id == original_row.id

    def test_raises_when_token_not_found(self, db_conn):
        document_id = db_conn.execute(
            text("INSERT INTO documents (title, text) VALUES ('t', 't') RETURNING id")
        ).scalar_one()

        try:
            correct_reading(db_conn, document_id, -1, "さんまた")
            assert False, "expected TokenNotFound"
        except TokenNotFound:
            pass
