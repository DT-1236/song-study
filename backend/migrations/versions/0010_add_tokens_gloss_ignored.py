"""add gloss_ignored to tokens

Set when a user marks a token as needing no gloss — a word no dictionary
has an entry for, like a name — so it stops being flagged as missing one.

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-13 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "ALTER TABLE tokens ADD COLUMN gloss_ignored BOOLEAN NOT NULL DEFAULT FALSE;"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE tokens DROP COLUMN gloss_ignored;")
