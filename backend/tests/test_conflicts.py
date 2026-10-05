"""Regression tests for app.conflicts.

All DB-integration (`db_conn` from conftest.py, `make_token` from
support.py) — every case here reproduces a real bug found this session:

- resolve_conflict originally only updated furigana_override on a switch,
  leaving a stale gloss paired with the newly-selected reading.
- attach_glosses used to clobber a user's correct_reading correction on a
  later gap-fill pass (fixed elsewhere, in glosses.py, but correct_reading's
  own "preserve the original as an unselected row" behavior is what makes
  redo possible at all, so it's covered here).
- Concurrent correct_reading calls for the same token raced past the
  "one selected row per token" unique index before the FOR UPDATE locks
  were added. Covered with two connections over committed rows (see
  `committed_engine`), since neither can see the other's uncommitted work.
"""

from __future__ import annotations

import json

from sqlalchemy import text

from app.conflicts import (
    ConflictNotFound,
    TokenNotFound,
    _recompute_phrase_furigana,
    correct_reading,
    create_conflicts,
    create_phrase_conflicts,
    repair_gloss_links,
    resolve_conflict,
    resolve_phrase_furigana,
    unmerge_phrase,
)
from app.glosses import attach_glosses
from app.tokenization import TokenRecord
from tests.support import TEST_USER_ID, BackgroundCall, make_token, wait_for_lock_wait


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
            text(
                f"INSERT INTO documents (title, text, owner_id) VALUES ('t', 't', {TEST_USER_ID}) RETURNING id"
            )
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

    def test_flagged_record_gets_a_selected_default_plus_unselected_alternatives(
        self, db_conn
    ):
        document_id = db_conn.execute(
            text(
                f"INSERT INTO documents (title, text, owner_id) VALUES ('t', 't', {TEST_USER_ID}) RETURNING id"
            )
        ).scalar_one()
        token_id = make_token(
            db_conn, document_id=document_id, position=0, surface="今日"
        )

        alt_option = {
            "reading": "こんにち",
            "furigana_spans": [
                {"start": 0, "end": 2, "text": "今日", "reading": "こんにち"}
            ],
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
            furigana_spans=[
                {"start": 0, "end": 2, "text": "今日", "reading": "きょう"}
            ],
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


class TestPhraseConflicts:
    """Phrase suggestions, from their conflict rows through accepting and
    splitting one."""

    def _seed_phrase_tokens(self, conn):
        # この/期/に/及ん/で, whose idiom reads 期 as ご, unlike the token.
        document_id = conn.execute(
            text(
                f"INSERT INTO documents (title, text, owner_id) VALUES ('t', 't', {TEST_USER_ID}) RETURNING id"
            )
        ).scalar_one()
        # Real token data, so each token's own gloss after a split differs.
        tokens_data = [
            ("この", "この", "この", "コノ", ["連体詞", "*", "*", "*", "*", "*"]),
            ("期", "期", "期", "キ", ["名詞", "普通名詞", "一般", "*", "*", "*"]),
            ("に", "に", "に", "ニ", ["助詞", "格助詞", "*", "*", "*", "*"]),
            (
                "及ん",
                "及ぶ",
                "及ぶ",
                "オヨン",
                ["動詞", "一般", "*", "*", "五段-バ行", "連用形-撥音便"],
            ),
            ("で", "で", "で", "デ", ["助詞", "接続助詞", "*", "*", "*", "*"]),
        ]
        token_ids = [
            make_token(
                conn,
                document_id=document_id,
                position=position,
                surface=surface,
                dictionary_form=dictionary_form,
                normalized_form=normalized_form,
                reading_katakana=reading_katakana,
                part_of_speech=part_of_speech,
            )
            for position, (
                surface,
                dictionary_form,
                normalized_form,
                reading_katakana,
                part_of_speech,
            ) in enumerate(tokens_data)
        ]
        record = TokenRecord(
            position=0,
            char_begin=0,
            char_end=7,
            surface="この",
            dictionary_form="この",
            normalized_form="この",
            reading_katakana="コノ",
            part_of_speech=["連体詞", "*", "*", "*", "*", "*"],
            is_oov=False,
            furigana_spans=[],
            needs_review=False,
            review_reason=None,
            conflict_options=[],
            phrase_suggestion={
                "surface": "この期に及んで",
                "lookup_form": "この期に及んで",
                "reading": "このごにおよんで",
                "token_count": 5,
            },
        )
        create_phrase_conflicts(conn, document_id, [record], [])
        return document_id, token_ids

    def test_create_phrase_conflicts_inserts_one_unselected_row(self, db_conn):
        _document_id, token_ids = self._seed_phrase_tokens(db_conn)

        rows = _conflicts_for(db_conn, token_ids[0])
        assert len(rows) == 1
        assert rows[0].kind == "phrase"
        assert rows[0].selected is False
        assert rows[0].value == {
            "surface": "この期に及んで",
            "lookup_form": "この期に及んで",
            "reading": "このごにおよんで",
            "token_count": 5,
        }
        # Only the run's first token gets a row.
        assert _conflicts_for(db_conn, token_ids[1]) == []

    def test_no_rows_when_no_token_has_a_suggestion(self, db_conn):
        document_id = db_conn.execute(
            text(
                f"INSERT INTO documents (title, text, owner_id) VALUES ('t', 't', {TEST_USER_ID}) RETURNING id"
            )
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
            part_of_speech=["名詞", "*", "*", "*", "*", "*"],
            is_oov=False,
            furigana_spans=[],
            needs_review=False,
            review_reason=None,
            conflict_options=[],
        )
        create_phrase_conflicts(db_conn, document_id, [record], [])

        assert _conflicts_for(db_conn, token_id) == []

    def test_accepting_a_phrase_suggestion_groups_and_reglosses_every_member(
        self, db_conn
    ):
        document_id, token_ids = self._seed_phrase_tokens(db_conn)
        phrase_conflict_id = _conflicts_for(db_conn, token_ids[0])[0].id
        original_gloss_ids = [
            _token_row(db_conn, tid).gloss_lookup_id for tid in token_ids
        ]

        resolve_conflict(db_conn, document_id, token_ids[0], phrase_conflict_id)

        rows = _conflicts_for(db_conn, token_ids[0])
        assert rows[0].selected is True

        phrase_positions = db_conn.execute(
            text(
                "SELECT position, gloss_lookup_id, phrase_start_position FROM tokens WHERE document_id = :d ORDER BY position"
            ),
            {"d": document_id},
        ).all()
        assert [row.phrase_start_position for row in phrase_positions] == [
            0,
            0,
            0,
            0,
            0,
        ]
        gloss_ids = {row.gloss_lookup_id for row in phrase_positions}
        assert len(gloss_ids) == 1
        # Not left on any member's own gloss.
        assert gloss_ids.isdisjoint(original_gloss_ids)

        entry = db_conn.execute(
            text("SELECT lookup_form, reading FROM gloss_lookups WHERE id = :id"),
            {"id": gloss_ids.pop()},
        ).one()
        assert entry.lookup_form == "この期に及んで"
        assert entry.reading == "このごにおよんで"

    def test_accepting_recomputes_furigana_from_the_phrases_own_reading(self, db_conn):
        # 期 reads き on its own, but ご in the phrase.
        document_id, token_ids = self._seed_phrase_tokens(db_conn)
        phrase_conflict_id = _conflicts_for(db_conn, token_ids[0])[0].id

        resolve_conflict(db_conn, document_id, token_ids[0], phrase_conflict_id)

        this_ = _token_row(db_conn, token_ids[0])
        period = _token_row(db_conn, token_ids[1])
        ni = _token_row(db_conn, token_ids[2])
        oyon = _token_row(db_conn, token_ids[3])
        de = _token_row(db_conn, token_ids[4])
        assert this_.furigana_override == [
            {"start": 0, "end": 2, "text": "この", "reading": None}
        ]
        assert period.furigana_override == [
            {"start": 0, "end": 1, "text": "期", "reading": "ご"}
        ]
        assert ni.furigana_override == [
            {"start": 0, "end": 1, "text": "に", "reading": None}
        ]
        assert oyon.furigana_override == [
            {"start": 0, "end": 1, "text": "及", "reading": "およ"},
            {"start": 1, "end": 2, "text": "ん", "reading": None},
        ]
        assert de.furigana_override == [
            {"start": 0, "end": 1, "text": "で", "reading": None}
        ]

    def test_unmerge_reverts_every_member_to_its_own_gloss(self, db_conn):
        document_id, token_ids = self._seed_phrase_tokens(db_conn)
        phrase_conflict_id = _conflicts_for(db_conn, token_ids[0])[0].id
        resolve_conflict(db_conn, document_id, token_ids[0], phrase_conflict_id)

        # From a member other than the first.
        affected = unmerge_phrase(db_conn, document_id, token_ids[2])

        assert sorted(affected) == sorted(token_ids)
        rows = db_conn.execute(
            text(
                "SELECT position, gloss_lookup_id, phrase_start_position FROM tokens "
                "WHERE document_id = :d ORDER BY position"
            ),
            {"d": document_id},
        ).all()
        assert all(row.phrase_start_position is None for row in rows)
        # Each token is glossable, so each gets a gloss of its own back.
        gloss_ids = {row.gloss_lookup_id for row in rows}
        assert len(gloss_ids) == 5

    def test_an_accepted_phrase_with_an_unlinked_token_is_glossed_as_the_phrase(
        self, db_conn
    ):
        document_id, token_ids = self._seed_phrase_tokens(db_conn)
        phrase_conflict_id = _conflicts_for(db_conn, token_ids[0])[0].id
        resolve_conflict(db_conn, document_id, token_ids[0], phrase_conflict_id)
        phrase_gloss_id = _token_row(db_conn, token_ids[0]).gloss_lookup_id
        # As a migration clearing stale glosses would leave it.
        db_conn.execute(
            text("UPDATE tokens SET gloss_lookup_id = NULL WHERE id = :id"),
            {"id": token_ids[2]},
        )

        repair_gloss_links(db_conn, document_id)

        rows = db_conn.execute(
            text(
                "SELECT gloss_lookup_id, phrase_start_position FROM tokens WHERE document_id = :d"
            ),
            {"d": document_id},
        ).all()
        assert {row.gloss_lookup_id for row in rows} == {phrase_gloss_id}
        assert {row.phrase_start_position for row in rows} == {0}

    def test_attach_glosses_leaves_an_unlinked_group_member_to_its_group(self, db_conn):
        # Glossed as itself, 期 would be linked to き's gloss, and a later
        # attach_group_glosses would find nothing left to repair.
        document_id, token_ids = self._seed_phrase_tokens(db_conn)
        phrase_conflict_id = _conflicts_for(db_conn, token_ids[0])[0].id
        resolve_conflict(db_conn, document_id, token_ids[0], phrase_conflict_id)
        db_conn.execute(
            text("UPDATE tokens SET gloss_lookup_id = NULL WHERE id = :id"),
            {"id": token_ids[1]},
        )

        attach_glosses(db_conn, document_id)

        assert _token_row(db_conn, token_ids[1]).gloss_lookup_id is None

    def test_unmerge_deselects_the_phrase_conflict_so_it_can_be_reaccepted(
        self, db_conn
    ):
        document_id, token_ids = self._seed_phrase_tokens(db_conn)
        phrase_conflict_id = _conflicts_for(db_conn, token_ids[0])[0].id
        resolve_conflict(db_conn, document_id, token_ids[0], phrase_conflict_id)

        unmerge_phrase(db_conn, document_id, token_ids[0])

        # Left selected, the phrase's reading was used for この's own gloss,
        # and the suggestion couldn't be accepted again.
        rows = _conflicts_for(db_conn, token_ids[0])
        assert rows[0].selected is False

        head = db_conn.execute(
            text("SELECT gloss_lookup_id FROM tokens WHERE id = :id"),
            {"id": token_ids[0]},
        ).one()
        entries = db_conn.execute(
            text("SELECT reading, entries FROM gloss_lookups WHERE id = :id"),
            {"id": head.gloss_lookup_id},
        ).one()
        assert entries.reading != "このごにおよんで"
        assert entries.entries != []

        # It can be accepted again.
        second_accept = resolve_conflict(
            db_conn, document_id, token_ids[0], phrase_conflict_id
        )
        assert sorted(second_accept) == sorted(token_ids)
        assert _conflicts_for(db_conn, token_ids[0])[0].selected is True

    def test_selecting_an_ordinary_reading_on_a_merged_token_unmerges_the_whole_group(
        self, db_conn
    ):
        # Otherwise the picked token alone is glossed as itself while the rest
        # still show the phrase.
        document_id, token_ids = self._seed_phrase_tokens(db_conn)
        phrase_conflict_id = _conflicts_for(db_conn, token_ids[0])[0].id
        resolve_conflict(db_conn, document_id, token_ids[0], phrase_conflict_id)
        assert all(
            db_conn.execute(
                text("SELECT phrase_start_position FROM tokens WHERE id = :id"),
                {"id": tid},
            ).scalar_one()
            is not None
            for tid in token_ids
        )

        # Any reading option will do.
        alt_conflict_id = db_conn.execute(
            text(
                """
                INSERT INTO conflicts (token_id, kind, value, selected)
                VALUES (:token_id, 'heteronym', '{"reading": "こ", "furigana_spans": [], "citation_reading": "こ"}', FALSE)
                RETURNING id
                """
            ),
            {"token_id": token_ids[0]},
        ).scalar_one()

        affected = resolve_conflict(db_conn, document_id, token_ids[0], alt_conflict_id)

        assert set(affected) == set(token_ids)
        rows = db_conn.execute(
            text(
                "SELECT id, phrase_start_position, gloss_lookup_id FROM tokens "
                "WHERE id = ANY(:ids) ORDER BY position"
            ),
            {"ids": token_ids},
        ).all()
        assert all(row.phrase_start_position is None for row in rows)
        # Each on its own gloss.
        gloss_ids = {row.gloss_lookup_id for row in rows}
        assert len(gloss_ids) == len(token_ids)
        # The suggestion can be accepted again, as after a split.
        assert _conflicts_for(db_conn, token_ids[0])[0].selected is False

    def test_unmerge_is_a_noop_for_a_token_that_was_never_merged(self, db_conn):
        document_id = db_conn.execute(
            text(
                f"INSERT INTO documents (title, text, owner_id) VALUES ('t', 't', {TEST_USER_ID}) RETURNING id"
            )
        ).scalar_one()
        token_id = make_token(db_conn, document_id=document_id, position=0)

        assert unmerge_phrase(db_conn, document_id, token_id) == []

    def test_unmerge_raises_for_a_token_outside_the_document(self, db_conn):
        document_id = db_conn.execute(
            text(
                f"INSERT INTO documents (title, text, owner_id) VALUES ('t', 't', {TEST_USER_ID}) RETURNING id"
            )
        ).scalar_one()
        other_document_id = db_conn.execute(
            text(
                f"INSERT INTO documents (title, text, owner_id) VALUES ('t2', 't2', {TEST_USER_ID}) RETURNING id"
            )
        ).scalar_one()
        token_id = make_token(db_conn, document_id=other_document_id, position=0)

        try:
            unmerge_phrase(db_conn, document_id, token_id)
            assert False, "expected TokenNotFound"
        except TokenNotFound:
            pass

    def test_unmerge_clears_the_phrase_furigana_override_and_its_conflicts(
        self, db_conn
    ):
        document_id, token_ids = self._seed_phrase_tokens(db_conn)
        phrase_conflict_id = _conflicts_for(db_conn, token_ids[0])[0].id
        resolve_conflict(db_conn, document_id, token_ids[0], phrase_conflict_id)
        assert _token_row(db_conn, token_ids[1]).furigana_override is not None

        unmerge_phrase(db_conn, document_id, token_ids[0])

        assert all(
            _token_row(db_conn, tid).furigana_override is None for tid in token_ids
        )


class TestPhraseFurigana:
    """A merged phrase's furigana from its own reading, and picking between
    its valid splits."""

    def test_leaves_furigana_untouched_when_the_reading_does_not_align(self, db_conn):
        # まにうける spells a る that 真に受け doesn't, and the kana に and け
        # leave nowhere to put it.
        document_id = db_conn.execute(
            text(
                f"INSERT INTO documents (title, text, owner_id) VALUES ('t', 't', {TEST_USER_ID}) RETURNING id"
            )
        ).scalar_one()
        shin = make_token(db_conn, document_id=document_id, position=0, surface="真")
        ni = make_token(db_conn, document_id=document_id, position=1, surface="に")
        uke = make_token(db_conn, document_id=document_id, position=2, surface="受け")
        originals = [
            _token_row(db_conn, tid).furigana_override for tid in (shin, ni, uke)
        ]

        _recompute_phrase_furigana(
            db_conn,
            document_id,
            position=0,
            token_count=3,
            reading_hiragana="まにうける",
        )

        assert [
            _token_row(db_conn, tid).furigana_override for tid in (shin, ni, uke)
        ] == originals

    def test_offers_a_pick_for_a_genuinely_ambiguous_run(self, db_conn):
        # 六右 read むゆう splits as む/ゆう or むゆ/う.
        document_id = db_conn.execute(
            text(
                f"INSERT INTO documents (title, text, owner_id) VALUES ('t', 't', {TEST_USER_ID}) RETURNING id"
            )
        ).scalar_one()
        roku = make_token(db_conn, document_id=document_id, position=0, surface="六")
        u = make_token(db_conn, document_id=document_id, position=1, surface="右")

        _recompute_phrase_furigana(
            db_conn, document_id, position=0, token_count=2, reading_hiragana="むゆう"
        )

        # The first valid split applied immediately as the default.
        assert _token_row(db_conn, roku).furigana_override == [
            {"start": 0, "end": 1, "text": "六", "reading": "む"}
        ]
        assert _token_row(db_conn, u).furigana_override == [
            {"start": 0, "end": 1, "text": "右", "reading": "ゆう"}
        ]

        alt_conflicts = _conflicts_for(db_conn, roku)
        assert len(alt_conflicts) == 1
        assert alt_conflicts[0].kind == "phrase_furigana"
        assert alt_conflicts[0].selected is False

        resolve_phrase_furigana(db_conn, document_id, alt_conflicts[0].id)

        assert _token_row(db_conn, roku).furigana_override == [
            {"start": 0, "end": 1, "text": "六", "reading": "むゆ"}
        ]
        assert _token_row(db_conn, u).furigana_override == [
            {"start": 0, "end": 1, "text": "右", "reading": "う"}
        ]
        # Applying an alternative leaves it unselected.
        assert _conflicts_for(db_conn, roku)[0].selected is False

    def test_raises_for_a_nonexistent_conflict_id(self, db_conn):
        document_id = db_conn.execute(
            text(
                f"INSERT INTO documents (title, text, owner_id) VALUES ('t', 't', {TEST_USER_ID}) RETURNING id"
            )
        ).scalar_one()

        try:
            resolve_phrase_furigana(db_conn, document_id, -1)
            assert False, "expected ConflictNotFound"
        except ConflictNotFound:
            pass


class TestResolveConflict:
    def _seed_heteronym_token(self, conn):
        document_id = conn.execute(
            text(
                f"INSERT INTO documents (title, text, owner_id) VALUES ('t', 't', {TEST_USER_ID}) RETURNING id"
            )
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
            "furigana_spans": [
                {"start": 0, "end": 2, "text": "今日", "reading": "きょう"}
            ],
            "citation_reading": "きょう",
        }
        alt_value = {
            "reading": "こんにち",
            "furigana_spans": [
                {"start": 0, "end": 2, "text": "今日", "reading": "こんにち"}
            ],
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
        document_id, _token_id, default_id, _alt_id = self._seed_heteronym_token(
            db_conn
        )
        other_token_id = make_token(db_conn, document_id=document_id, position=1)

        try:
            resolve_conflict(db_conn, document_id, other_token_id, default_id)
            assert False, "expected ConflictNotFound"
        except ConflictNotFound:
            pass


class TestCorrectReading:
    def _seed_uncorrected_token(self, conn):
        document_id = conn.execute(
            text(
                f"INSERT INTO documents (title, text, owner_id) VALUES ('t', 't', {TEST_USER_ID}) RETURNING id"
            )
        ).scalar_one()
        token_id = make_token(
            conn,
            document_id=document_id,
            surface="三股",
            dictionary_form="三股",
            normalized_form="三股",
            reading_katakana="ミマタ",
            char_end=2,
            furigana_spans=[
                {"start": 0, "end": 2, "text": "三股", "reading": "みまた"}
            ],
        )
        return document_id, token_id

    def test_first_correction_preserves_sudachis_original_as_an_unselected_row(
        self, db_conn
    ):
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
        assert (
            "".join(s["reading"] or "" for s in token.furigana_override) == "さんまた"
        )

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

    def test_can_redo_back_to_the_preserved_original_via_resolve_conflict(
        self, db_conn
    ):
        document_id, token_id = self._seed_uncorrected_token(db_conn)

        correct_reading(db_conn, document_id, token_id, "さんまた")
        rows = _conflicts_for(db_conn, token_id)
        original_row = next(r for r in rows if r.value["reading"] == "みまた")

        resolve_conflict(db_conn, document_id, token_id, original_row.id)

        token = _token_row(db_conn, token_id)
        assert "".join(s["reading"] or "" for s in token.furigana_override) == "みまた"
        rows = _conflicts_for(db_conn, token_id)
        assert next(r for r in rows if r.selected).id == original_row.id

    def test_concurrent_corrections_serialize_instead_of_racing(self, committed_engine):
        with committed_engine.begin() as conn:
            document_id, token_id = self._seed_uncorrected_token(conn)

        def correct_in_own_transaction():
            with committed_engine.begin() as conn:
                correct_reading(conn, document_id, token_id, "みつまた")

        with committed_engine.connect() as first_conn:
            correct_reading(first_conn, document_id, token_id, "さんまた")
            second = BackgroundCall(correct_in_own_transaction)
            wait_for_lock_wait()
            first_conn.commit()
        second.outcome()

        with committed_engine.connect() as conn:
            rows = _conflicts_for(conn, token_id)
        # The second call saw the first's committed rows: one preserved
        # original, not two, and only its own reading left selected.
        assert sorted(r.value["reading"] for r in rows) == sorted(
            ["みまた", "さんまた", "みつまた"]
        )
        assert [r.value["reading"] for r in rows if r.selected] == ["みつまた"]

    def test_raises_when_token_not_found(self, db_conn):
        document_id = db_conn.execute(
            text(
                f"INSERT INTO documents (title, text, owner_id) VALUES ('t', 't', {TEST_USER_ID}) RETURNING id"
            )
        ).scalar_one()

        try:
            correct_reading(db_conn, document_id, -1, "さんまた")
            assert False, "expected TokenNotFound"
        except TokenNotFound:
            pass
