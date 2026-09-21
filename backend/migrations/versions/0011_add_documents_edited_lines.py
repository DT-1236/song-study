"""add edited_lines to documents

The document's own line timings, as edited on its page, in the same shape
as lrclib_lines. They're kept apart from lrclib_lines, which is replaced
with LRCLIB's timings on every load. edited_lines_text is the text they were
made for, so they can be dropped once the document's text no longer matches
it. Both are NULL exactly when there are no edits.

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-14 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        ALTER TABLE documents
            ADD COLUMN edited_lines JSONB,
            ADD COLUMN edited_lines_text TEXT,
            ADD CONSTRAINT documents_edited_lines_text_set_with_lines
            CHECK ((edited_lines IS NULL) = (edited_lines_text IS NULL));
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "ALTER TABLE documents DROP COLUMN edited_lines_text, DROP COLUMN edited_lines;"
    )
