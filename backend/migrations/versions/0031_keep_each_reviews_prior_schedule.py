"""keep the schedule a card had before each review

So that a review can be undone: a card corrected to another word right after
its answer had been asking about the wrong word, and its review is withdrawn,
with the card put back the way it was. Reviews logged before this have no
prior schedule kept, and stand.

Revision ID: 0031
Revises: 0030
Create Date: 2026-10-07 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0031"
down_revision: str | Sequence[str] | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # study_cards' scheduling columns, as they were. Only state and due are
    # never null on a card, so they say whether the rest was kept.
    op.execute(
        """
        ALTER TABLE study_reviews
            ADD COLUMN prev_state       SMALLINT CHECK (prev_state IN (1, 2, 3)),
            ADD COLUMN prev_step        SMALLINT,
            ADD COLUMN prev_stability   DOUBLE PRECISION,
            ADD COLUMN prev_difficulty  DOUBLE PRECISION,
            ADD COLUMN prev_due         TIMESTAMPTZ,
            ADD COLUMN prev_last_review TIMESTAMPTZ,
            ADD CHECK ((prev_state IS NULL) = (prev_due IS NULL));
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        """
        ALTER TABLE study_reviews
            DROP COLUMN prev_state,
            DROP COLUMN prev_step,
            DROP COLUMN prev_stability,
            DROP COLUMN prev_difficulty,
            DROP COLUMN prev_due,
            DROP COLUMN prev_last_review;
        """
    )
