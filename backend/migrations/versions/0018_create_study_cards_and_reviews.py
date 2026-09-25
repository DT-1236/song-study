"""create study_cards and study_reviews

A card names what it tests by value: a word by its gloss key (lookup_form,
reading), or a grammar term by its normalized form with no reading. It has no
foreign key into gloss_lookups, which is only a cache and is emptied whenever
gloss logic changes (0013-0015): a cascade from there would delete review
history, and anything weaker would leave cards pointing at nothing.

The scheduling columns are py-fsrs's Card, whose new card is state 1
(Learning) at step 0, due now, with no stability or difficulty yet.

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-24 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0018"
down_revision: str | Sequence[str] | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        CREATE TABLE study_cards (
            id                     SERIAL PRIMARY KEY,
            user_id                INTEGER NOT NULL REFERENCES users (id),
            kind                   TEXT NOT NULL CHECK (kind IN ('recognition', 'grammar')),
            lookup_form            TEXT NOT NULL,
            reading                TEXT,
            -- A second spelling to look the word up under when lookup_form
            -- has no JMDict entry, as the tokens it came from were glossed.
            alt_lookup_form        TEXT,
            state                  SMALLINT NOT NULL DEFAULT 1 CHECK (state IN (1, 2, 3)),
            step                   SMALLINT DEFAULT 0,
            stability              DOUBLE PRECISION,
            difficulty             DOUBLE PRECISION,
            due                    TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_review            TIMESTAMPTZ,
            -- Removed from study, keeping its history for a later re-add.
            suspended              BOOLEAN NOT NULL DEFAULT FALSE,
            first_seen_document_id INTEGER REFERENCES documents (id) ON DELETE SET NULL,
            created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
            CHECK ((kind = 'grammar') = (reading IS NULL)),
            CONSTRAINT study_cards_word_key
                UNIQUE NULLS NOT DISTINCT (user_id, kind, lookup_form, reading)
        );

        CREATE TABLE study_reviews (
            id          SERIAL PRIMARY KEY,
            -- No cascade: a card with reviews is never deleted.
            card_id     INTEGER NOT NULL REFERENCES study_cards (id),
            -- The song whose line was played.
            document_id INTEGER REFERENCES documents (id) ON DELETE SET NULL,
            reviewed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            correct     BOOLEAN NOT NULL,
            duration_ms INTEGER NOT NULL,
            -- The latency thresholds `rating` was computed with, so changing
            -- them later doesn't reinterpret it.
            fast_ms     INTEGER NOT NULL,
            slow_ms     INTEGER NOT NULL,
            rating      SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 4)
        );

        CREATE INDEX study_reviews_card_id_idx ON study_reviews (card_id);
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TABLE study_reviews; DROP TABLE study_cards;")
