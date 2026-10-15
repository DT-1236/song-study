"""record when a document's last check against LRCLIB failed, and why

Opening a document whose check failed a moment ago shows the recorded error
instead of asking LRCLIB again, so an outage doesn't make every load wait out
the request timeout. Both are cleared by the next successful check.

Revision ID: 0038
Revises: 0037
Create Date: 2026-10-15 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0038"
down_revision: str | Sequence[str] | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "ALTER TABLE documents ADD COLUMN lrclib_failed_at TIMESTAMPTZ, "
        "ADD COLUMN lrclib_failure TEXT"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "ALTER TABLE documents DROP COLUMN lrclib_failed_at, DROP COLUMN lrclib_failure"
    )
