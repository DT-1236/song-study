"""store a JMDict lookup that found nothing under a source of its own

A gloss_lookups row of ([], 'jmdict') meant "looked up, nothing found", so
telling one apart from a real headword took reading its entries. Such a miss
is now stored as 'jmdict_miss', and 'jmdict' always means a headword was
found.

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-05 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0021"
down_revision: str | Sequence[str] | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        UPDATE gloss_lookups SET source = 'jmdict_miss'
        WHERE source = 'jmdict' AND entries = CAST('[]' AS JSONB);
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "UPDATE gloss_lookups SET source = 'jmdict' WHERE source = 'jmdict_miss';"
    )
