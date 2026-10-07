"""keep the schedule each review gave its card

So that undoing a review can tell it's still what set the card's schedule by
comparing the schedule itself, rather than trusting every change to one to
set last_review to its own time. A review since 0031 that's still its card's
latest gets the card's schedule now; any other has none, and stands.

Revision ID: 0032
Revises: 0031
Create Date: 2026-10-07 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0032"
down_revision: str | Sequence[str] | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # study_cards' scheduling columns, as the review left them, mirroring
    # 0031's prev_*.
    op.execute(
        """
        ALTER TABLE study_reviews
            ADD COLUMN next_state       SMALLINT CHECK (next_state IN (1, 2, 3)),
            ADD COLUMN next_step        SMALLINT,
            ADD COLUMN next_stability   DOUBLE PRECISION,
            ADD COLUMN next_difficulty  DOUBLE PRECISION,
            ADD COLUMN next_due         TIMESTAMPTZ,
            ADD COLUMN next_last_review TIMESTAMPTZ,
            ADD CHECK ((next_state IS NULL) = (next_due IS NULL));
        """
    )
    # Until now, a card's last_review being a review's time was what said the
    # review set its schedule.
    op.execute(
        """
        UPDATE study_reviews r
        SET next_state = c.state, next_step = c.step, next_stability = c.stability,
            next_difficulty = c.difficulty, next_due = c.due,
            next_last_review = c.last_review
        FROM study_cards c
        WHERE c.id = r.card_id AND r.prev_state IS NOT NULL
          AND r.reviewed_at = c.last_review
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        """
        ALTER TABLE study_reviews
            DROP COLUMN next_state,
            DROP COLUMN next_step,
            DROP COLUMN next_stability,
            DROP COLUMN next_difficulty,
            DROP COLUMN next_due,
            DROP COLUMN next_last_review;
        """
    )
