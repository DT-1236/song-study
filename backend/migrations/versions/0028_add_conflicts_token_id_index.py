"""add non-partial index on conflicts (token_id)

The partial index conflicts_one_selected_per_token only indexes rows
WHERE selected, so queries that scan all conflicts for a token must
scan the entire table. Add a non-partial index to support queries like
get_alternate_readings and token reads in main.py.

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-07 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0028"
down_revision: str | Sequence[str] | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        CREATE INDEX conflicts_token_id ON conflicts (token_id);
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX conflicts_token_id;")
