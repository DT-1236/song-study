"""add phrase_start_position to tokens

The position of the first token of the group a token is merged into (a
predicate with its grammar, or an accepted phrase), shared by every token in
the group along with its gloss_lookup_id. NULL for a token that isn't
merged.

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-15 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: Union[str, Sequence[str], None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TABLE tokens ADD COLUMN phrase_start_position INT;")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE tokens DROP COLUMN phrase_start_position;")
