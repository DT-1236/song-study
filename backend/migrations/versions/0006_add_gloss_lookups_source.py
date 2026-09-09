"""add source column to gloss_lookups

Lets us tell a real JMDict miss apart from a word we deliberately routed
somewhere else (currently: a stubbed-out English lookup for Latin-script
words, so JMDict — which has no English headwords — isn't queried at all
for something that can never match). Once a real English dictionary lookup
exists, this is what lets it find and re-process exactly the stubbed rows.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-06 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0006'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        ALTER TABLE gloss_lookups
            ADD COLUMN source TEXT NOT NULL DEFAULT 'jmdict';
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE gloss_lookups DROP COLUMN source;")
