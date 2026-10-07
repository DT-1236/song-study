"""key a card for a word picked for a piece of katakana by its JMDict entry

A card names its word by gloss key, (spelling, reading), which can't tell
apart two entries read alike and written alike: two written in kana (うん,
"yes" and "some"), or two usually written with the same kanji (元 read もと).
A word picked for a piece of katakana names its entry (0029), so its card now
does too, in a nullable idseq, when its gloss key has other entries: two
picked entries written alike are two cards, and each card's answer is its
own entry's senses alone. A pick its key already says (合う read あう) stays
the card of the word written in kanji.

A card already made for such a word moves to its entry, so the tokens that
pick it still lead to it. A card doesn't record which token it was made
from, so where tokens pick two entries keyed alike, it moves to one picked
in the song it was first seen in, if any; and a word keyed alike that wasn't
picked (written in kanji, or a guess at katakana) is left without a card
until it's added again.

Revision ID: 0030
Revises: 0029
Create Date: 2026-10-07 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0030"
down_revision: str | Sequence[str] | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        ALTER TABLE study_cards
            ADD COLUMN idseq INTEGER,
            ADD CHECK (idseq IS NULL OR kind = 'recognition'),
            DROP CONSTRAINT study_cards_word_key,
            ADD CONSTRAINT study_cards_word_key
                UNIQUE NULLS NOT DISTINCT (user_id, kind, lookup_form, reading, idseq);
        """
    )
    # Each pick's card key: its entry's usual kanji form (a form it marks
    # common, or else its first), or its reading for an entry with none, read
    # the piece's way, from the gloss cache's row its word was offered from.
    # A card whose own row isn't cached any more is left as it is.
    op.execute(
        """
        UPDATE study_cards c SET idseq = p.idseq
        FROM (
            SELECT DISTINCT ON (card.id) card.id AS card_id, kp.idseq
            FROM katakana_picks kp
            JOIN tokens t ON t.id = kp.token_id
            JOIN documents d ON d.id = t.document_id
            JOIN gloss_lookups gl
              ON gl.lookup_form = kp.reading AND gl.reading = kp.reading
             AND gl.source = 'jmdict'
            CROSS JOIN jsonb_array_elements(gl.entries) AS e(entry)
            CROSS JOIN LATERAL (
                SELECT COALESCE(
                    (
                        SELECT f.form ->> 'text'
                        FROM jsonb_array_elements(e.entry -> 'kanji_forms')
                            WITH ORDINALITY AS f(form, ord)
                        ORDER BY jsonb_array_length(f.form -> 'pri') = 0, f.ord
                        LIMIT 1
                    ),
                    kp.reading
                ) AS spelling
            ) s
            JOIN study_cards card
              ON card.user_id = d.owner_id AND card.kind = 'recognition'
             AND card.lookup_form = s.spelling AND card.reading = kp.reading
            JOIN gloss_lookups own
              ON own.lookup_form = card.lookup_form AND own.reading = card.reading
             AND own.source = 'jmdict'
            WHERE (e.entry ->> 'idseq')::int = kp.idseq
              AND EXISTS (
                  SELECT 1 FROM jsonb_array_elements(own.entries) AS o(entry)
                  WHERE (o.entry ->> 'idseq')::int <> kp.idseq
              )
            ORDER BY card.id, t.document_id IS DISTINCT FROM card.first_seen_document_id,
                     t.document_id, t.position, kp.piece
        ) p
        WHERE c.id = p.card_id;
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Fails if a user has cards for two entries keyed alike: one of them would
    # have to go, with its history.
    op.execute(
        """
        ALTER TABLE study_cards
            DROP CONSTRAINT study_cards_word_key,
            DROP COLUMN idseq,
            ADD CONSTRAINT study_cards_word_key
                UNIQUE NULLS NOT DISTINCT (user_id, kind, lookup_form, reading);
        """
    )
