"""create conflicts table

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-06 10:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        CREATE TABLE conflicts (
            id           SERIAL PRIMARY KEY,
            token_id     INT NOT NULL REFERENCES tokens (id),

            kind         TEXT NOT NULL,     -- 'heteronym' | 'no_kana_anchor'
            value        JSONB NOT NULL,    -- {"reading": "...", "furigana_spans": [...]}

            selected     BOOLEAN NOT NULL DEFAULT FALSE,
            selected_at  TIMESTAMPTZ,

            created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX conflicts_one_selected_per_token
            ON conflicts (token_id)
            WHERE selected;
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TABLE conflicts;")
