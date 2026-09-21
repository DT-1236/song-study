"""create documents table

Revision ID: 0001
Revises:
Create Date: 2026-09-04 12:09:13.510184

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        CREATE TABLE documents (
            id               SERIAL PRIMARY KEY,
            title            TEXT NOT NULL,
            text             TEXT NOT NULL,
            youtube_video_id TEXT UNIQUE,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TABLE documents;")
