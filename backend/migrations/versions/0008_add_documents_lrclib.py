"""add LRCLIB source columns to documents

lrclib_uri is the LRCLIB API address a document's lyrics are loaded from;
while it's set, LRCLIB's text replaces the document's own. lrclib_lines is
the timing of each line of that text ([{"start", "end"}] in seconds, in
line order) — what playback highlights lines by, and what a later load is
compared against, so a timing-only update on LRCLIB doesn't discard the
readings picked for the document. NULL when the LRCLIB record only has
unsynced lyrics, or once the text is edited.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0008'
down_revision: Union[str, Sequence[str], None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        ALTER TABLE documents
            ADD COLUMN lrclib_uri   TEXT,
            ADD COLUMN lrclib_lines JSONB;
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        """
        ALTER TABLE documents
            DROP COLUMN lrclib_lines,
            DROP COLUMN lrclib_uri;
        """
    )
