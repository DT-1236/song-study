"""record the text a document's LRCLIB line timings were made for

Like edited_lines_text for edited_lines: the timings only apply while the
document's text is the one they were made for, so a writer that changes the
text needn't remember to clear them. Both are NULL exactly when there are no
timings.

Revision ID: 0036
Revises: 0035
Create Date: 2026-10-13 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0036"
down_revision: str | Sequence[str] | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        ALTER TABLE documents ADD COLUMN lrclib_lines_text TEXT;

        -- Every writer so far cleared the timings when it changed the text,
        -- so the stored ones are for the current text.
        UPDATE documents SET lrclib_lines_text = text WHERE lrclib_lines IS NOT NULL;

        ALTER TABLE documents
            ADD CONSTRAINT documents_lrclib_lines_text_set_with_lines
            CHECK ((lrclib_lines IS NULL) = (lrclib_lines_text IS NULL));
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        """
        UPDATE documents SET lrclib_lines = NULL WHERE lrclib_lines_text <> text;
        ALTER TABLE documents DROP COLUMN lrclib_lines_text;
        """
    )
