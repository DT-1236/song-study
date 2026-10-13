"""track each document's processing job

A document is processed (tokenized and glossed) by a background job rather
than within the request that asks for its tokens, so the job's claim and
whether it last failed are kept on the document, for whichever request asks
next.

Revision ID: 0033
Revises: 0032
Create Date: 2026-10-12 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0033"
down_revision: str | Sequence[str] | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        ALTER TABLE documents
            ADD COLUMN processing_started_at TIMESTAMPTZ,
            ADD COLUMN processing_failed     BOOLEAN NOT NULL DEFAULT FALSE;
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        """
        ALTER TABLE documents
            DROP COLUMN processing_started_at,
            DROP COLUMN processing_failed;
        """
    )
