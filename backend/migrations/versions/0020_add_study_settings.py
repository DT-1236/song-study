"""add the study settings: desired retention, and new cards per song per day

Desired retention is the user's alone, since a card is shared by every song
its word is in. The new-card limit belongs to a document, which has one
owner. The defaults are the ones docs/flashcards.md decides; the retention
range is the slider's, the lowest and highest target it offers.

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-25 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0020"
down_revision: str | Sequence[str] | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        ALTER TABLE users
            ADD COLUMN desired_retention DOUBLE PRECISION NOT NULL DEFAULT 0.90
                CHECK (desired_retention BETWEEN 0.75 AND 0.95);
        ALTER TABLE documents
            ADD COLUMN new_cards_per_day INTEGER NOT NULL DEFAULT 10
                CHECK (new_cards_per_day >= 0);
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        """
        ALTER TABLE documents DROP COLUMN new_cards_per_day;
        ALTER TABLE users DROP COLUMN desired_retention;
        """
    )
