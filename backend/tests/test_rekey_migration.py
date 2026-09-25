"""Migration 0019, which moves what was stored under a gloss key that read a
token's normalized form on its own (する as 為る read なる, "to become") to
the key that reads it as on the page."""

from __future__ import annotations

import importlib.util

import pytest
from sqlalchemy import text

from app.main import DocumentCreate, ReadingCorrection
from app.tokenization import mixed_reading
from tests.support import (
    BACKEND_DIR,
    TEST_USER_ID,
    add_token_card,
    correct_token_reading,
    create_document,
    get_document_tokens,
)

_MIGRATION = (
    BACKEND_DIR
    / "migrations"
    / "versions"
    / "0019_rekey_glosses_by_the_word_on_the_page.py"
)


def _rekey(engine) -> None:
    spec = importlib.util.spec_from_file_location("migration_0019", _MIGRATION)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as conn:
        migration.rekey(conn)


@pytest.fixture
def old_keys(monkeypatch):
    """Key glosses as before 0019: the normalized form read on its own."""
    for module in ("app.tokenization", "app.glosses", "app.conflicts"):
        monkeypatch.setattr(
            f"{module}.headword_reading",
            lambda normalized_form, dictionary_form: mixed_reading(normalized_form),
        )
    return monkeypatch


# JMDict's entries for する, "to do", and なる, "to become".
_TO_DO = 1157170
_TO_BECOME = 1375610


def _entries(gloss) -> set[int]:
    """The JMDict entries of a gloss's senses: its word's, for a group."""
    senses = gloss.pieces[0].senses if gloss.source == "composite" else gloss.senses
    return {sense.entry_idseq for sense in senses}


def test_suru_is_glossed_as_to_do(committed_engine):
    document_id = create_document(DocumentCreate(title="t", text="そうする。")).id
    [suru] = [t for t in get_document_tokens(document_id) if t.surface == "する"]

    assert (suru.gloss.lookup_form, suru.gloss.reading) == ("為る", "する")
    assert _entries(suru.gloss) == {_TO_DO}


def test_rekey_moves_what_the_old_key_stored(committed_engine, old_keys):
    document_id = create_document(
        DocumentCreate(title="t", text="そうする。もうする。料理をしていた。")
    ).id
    tokens = get_document_tokens(document_id)
    standalone, corrected = [t for t in tokens if t.surface == "する"]
    [group_head] = [t for t in tokens if t.surface == "し"]
    correct_token_reading(document_id, corrected.id, ReadingCorrection(reading="やる"))
    add_token_card(document_id, standalone.id)

    # As the old keys stored it.
    assert (standalone.gloss.lookup_form, standalone.gloss.reading) == ("為る", "なる")
    assert _entries(group_head.gloss) == {_TO_BECOME}

    old_keys.undo()
    _rekey(committed_engine)
    tokens = get_document_tokens(document_id)
    standalone, corrected = [t for t in tokens if t.surface == "する"]
    [group_head] = [t for t in tokens if t.surface == "し"]

    assert (standalone.gloss.lookup_form, standalone.gloss.reading) == ("為る", "する")
    assert _entries(standalone.gloss) == {_TO_DO}
    # Still grouped, and glossed again as a group.
    assert group_head.gloss.source == "composite"
    assert group_head.gloss.lookup_form == "為る＋て＋いる＋た"
    assert group_head.gloss.pieces[0].reading == "する"
    assert _entries(group_head.gloss) == {_TO_DO}
    # A typed correction stays selected; the original it preserved is keyed
    # the new way.
    assert {
        c.value["reading"]: (c.value["citation_reading"], c.selected)
        for c in corrected.conflicts
        if c.kind == "custom"
    } == {"する": ("する", False), "やる": ("やる", True)}
    assert corrected.gloss.reading == "やる"

    with committed_engine.connect() as conn:
        cards = conn.execute(
            text(
                "SELECT lookup_form, reading FROM study_cards WHERE user_id = :user_id"
            ),
            {"user_id": TEST_USER_ID},
        ).all()
    assert [tuple(card) for card in cards] == [("為る", "する")]


def test_rekey_leaves_a_card_the_user_has_under_both_keys(committed_engine):
    with committed_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO study_cards (user_id, kind, lookup_form, reading, alt_lookup_form)
                VALUES (:user_id, 'recognition', '為る', 'なる', 'する'),
                       (:user_id, 'recognition', '為る', 'する', 'する')
                """
            ),
            {"user_id": TEST_USER_ID},
        )

    _rekey(committed_engine)

    with committed_engine.connect() as conn:
        readings = (
            conn.execute(
                text("SELECT reading FROM study_cards ORDER BY reading"),
            )
            .scalars()
            .all()
        )
    assert readings == ["する", "なる"]
