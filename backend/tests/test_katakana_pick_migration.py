"""Migration 0029, which names the word picked for a piece of katakana by its
JMDict entry rather than its spelling."""

from __future__ import annotations

from alembic import command
from sqlalchemy import text

from tests.support import (
    alembic_config,
    create_tokenized_document,
    document_tokens,
    engine,
    get_piece_words,
)


def _picks() -> set[tuple]:
    with engine.connect() as conn:
        return set(conn.execute(text("SELECT * FROM katakana_picks")).all())


def test_a_pick_moves_to_the_entry_offered_for_its_spelling(committed_engine):
    # 僕/の/うん and 君/の/もと: うん is two words written in kana, and もと
    # two written 元.
    un_song = create_tokenized_document(text="ボクノウン。")
    moto_song = create_tokenized_document(text="キミノモト。")
    [un] = document_tokens(un_song, "ボクノウン")
    [moto] = document_tokens(moto_song, "キミノモト")
    # The first of each spelling, as the offer showed it.
    [yes, *_] = [
        o.idseq for o in get_piece_words(un_song, un.id, 2) if o.spelling == "うん"
    ]
    [origin, *_] = [
        o.idseq for o in get_piece_words(moto_song, moto.id, 2) if o.spelling == "元"
    ]

    config = alembic_config()
    command.downgrade(config, "0028")
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO katakana_picks (token_id, piece, reading, spelling)
                    VALUES (:un, 2, 'うん', 'うん'), (:moto, 2, 'もと', '元'),
                           -- No word read this way was ever offered.
                           (:un, 0, 'ぼくぼく', '僕')
                    """
                ),
                {"un": un.id, "moto": moto.id},
            )

        command.upgrade(config, "0029")
        assert _picks() == {(un.id, 2, "うん", yes), (moto.id, 2, "もと", origin)}

        command.downgrade(config, "0028")
        assert _picks() == {(un.id, 2, "うん", "うん"), (moto.id, 2, "もと", "元")}
    finally:
        command.upgrade(config, "head")
