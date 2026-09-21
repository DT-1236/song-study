"""create tokens table

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-04 12:09:13.722439

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        CREATE TABLE tokens (
            id               SERIAL PRIMARY KEY,
            document_id      INT NOT NULL REFERENCES documents (id),
            position         INT NOT NULL,

            char_begin       INT NOT NULL,
            char_end         INT NOT NULL,

            surface          TEXT NOT NULL,
            dictionary_form  TEXT NOT NULL,
            normalized_form  TEXT NOT NULL,
            reading_katakana TEXT NOT NULL,

            part_of_speech   JSONB NOT NULL,
            is_oov           BOOLEAN DEFAULT FALSE,

            furigana_spans   JSONB NOT NULL,       -- system-generated, always populated

            -- ambiguity flagging
            needs_review     BOOLEAN,
            review_reason    TEXT,                  -- 'oov' | 'heteronym' | 'no_kana_anchor' | NULL

            -- human override
            furigana_override JSONB,                -- same shape as furigana_spans, NULL until overridden
            overridden_by      TEXT,                -- user/account id, NULL until overridden
            overridden_at       TIMESTAMPTZ,          -- NULL until overridden

            start_time        NUMERIC(10,3),
            end_time            NUMERIC(10,3),

            created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TABLE tokens;")
