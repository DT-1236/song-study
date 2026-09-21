"""add lrclib_replaces_text to documents

Whether a linked document's lyrics are LRCLIB's (TRUE: they replace the
document's own, and follow LRCLIB's changes) or the document's own (FALSE:
only the track id is kept, and LRCLIB's line timings are used only while its
lyrics match the document's line for line). NULL exactly when the document
isn't linked. Documents linked before this was an option replaced their
lyrics.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-13 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TABLE documents ADD COLUMN lrclib_replaces_text BOOLEAN;")
    op.execute(
        "UPDATE documents SET lrclib_replaces_text = TRUE WHERE lrclib_uri IS NOT NULL;"
    )
    op.execute(
        """
        ALTER TABLE documents
            ADD CONSTRAINT documents_lrclib_replaces_text_set_when_linked
            CHECK ((lrclib_uri IS NULL) = (lrclib_replaces_text IS NULL));
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE documents DROP COLUMN lrclib_replaces_text;")
