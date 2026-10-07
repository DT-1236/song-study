"""Migration 0030, which keys a card for a word picked for a piece of katakana
by its JMDict entry when another is read and written alike."""

from __future__ import annotations

from alembic import command
from sqlalchemy import text

from tests.support import (
    FORMER,
    ORIGIN,
    SOME,
    TEST_USER_ID,
    TO_FIT,
    add_token_card,
    alembic_config,
    create_tokenized_document,
    document_tokens,
    engine,
    get_document_words,
    pick_piece_word,
    user_cards,
    word_key,
)


def _picked(text: str, piece: int, idseq: int) -> tuple[int, int]:
    """A song of `text`, a katakana token, with `idseq` picked for its
    `piece`, and the token's id."""
    document_id = create_tokenized_document(text=text)
    [token] = document_tokens(document_id, text.rstrip("。"))
    pick_piece_word(document_id, [token.id], piece, idseq)
    return document_id, token.id


def test_a_card_for_a_picked_word_moves_to_its_entry(committed_engine):
    un_song, un = _picked("ボクノウン。", 2, SOME)
    au_song, au = _picked("ボクノアイタイ。", 2, TO_FIT)
    add_token_card(un_song, un, piece=2)
    add_token_card(au_song, au, piece=2)

    config = alembic_config()
    command.downgrade(config, "0029")
    try:
        command.upgrade(config, "0030")
        # 合う is the only word written so and read あう.
        assert set(user_cards()) == {
            word_key("うん", "うん", SOME),
            word_key("合う", "あう"),
        }
    finally:
        command.upgrade(config, "head")


def test_a_card_picked_two_ways_moves_to_its_first_songs_entry(committed_engine):
    _picked("キミノモト。", 2, ORIGIN)
    former_song, _ = _picked("キミノモト。", 2, FORMER)
    # Caches the gloss of the card the picks would be.
    get_document_words(former_song)

    config = alembic_config()
    command.downgrade(config, "0029")
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO study_cards (
                        user_id, kind, lookup_form, reading, first_seen_document_id
                    )
                    VALUES (:user_id, 'recognition', '元', 'もと', :document_id)
                    """
                ),
                {"user_id": TEST_USER_ID, "document_id": former_song},
            )

        command.upgrade(config, "0030")
        assert set(user_cards()) == {word_key("元", "もと", FORMER)}

        command.downgrade(config, "0029")
        with engine.connect() as conn:
            assert conn.execute(
                text("SELECT lookup_form, reading FROM study_cards")
            ).all() == [("元", "もと")]
    finally:
        command.upgrade(config, "head")
