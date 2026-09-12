"""unique token position per document

create_conflicts (app/conflicts.py) maps in-memory TokenRecords back to
their just-inserted DB rows by looking up `position` per document_id and
trusting it's unique — nothing enforced that. A duplicate position for one
document would silently collapse in that lookup and could attach a conflict
to the wrong token instead of raising an error. This closes that gap at the
schema level, where the invariant actually belongs.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0007'
down_revision: Union[str, Sequence[str], None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        ALTER TABLE tokens
            ADD CONSTRAINT tokens_document_id_position_key UNIQUE (document_id, position);
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        """
        ALTER TABLE tokens
            DROP CONSTRAINT tokens_document_id_position_key;
        """
    )
