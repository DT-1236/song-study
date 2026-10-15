"""record when a document's lyrics were last checked against LRCLIB

A linked document is only re-fetched from LRCLIB once this is NULL or old
enough, so opening a document doesn't ask LRCLIB for lyrics it was just given.
NULL on existing documents means they're checked on their next load.

Revision ID: 0037
Revises: 0036
Create Date: 2026-10-15 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0037"
down_revision: str | Sequence[str] | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TABLE documents ADD COLUMN lrclib_checked_at TIMESTAMPTZ")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE documents DROP COLUMN lrclib_checked_at")
