"""create users table and give documents an owner

Every existing document is given to a seeded placeholder user (id 1), which
nobody logs in as; it exists only so the existing rows can have an owner, and
can be deleted once they've been reassigned. A YouTube video can now be used
by one document per owner rather than one overall.

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '0016'
down_revision: Union[str, Sequence[str], None] = '0015'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        CREATE TABLE users (
            id         SERIAL PRIMARY KEY,
            name       TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        INSERT INTO users (id, name) VALUES (1, 'default');
        SELECT setval(pg_get_serial_sequence('users', 'id'), 1);

        ALTER TABLE documents ADD COLUMN owner_id INTEGER REFERENCES users (id);
        UPDATE documents SET owner_id = 1;
        ALTER TABLE documents ALTER COLUMN owner_id SET NOT NULL;

        ALTER TABLE documents DROP CONSTRAINT documents_youtube_video_id_key;
        ALTER TABLE documents
            ADD CONSTRAINT documents_owner_id_youtube_video_id_key UNIQUE (owner_id, youtube_video_id);
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        """
        ALTER TABLE documents DROP CONSTRAINT documents_owner_id_youtube_video_id_key;
        ALTER TABLE documents ADD CONSTRAINT documents_youtube_video_id_key UNIQUE (youtube_video_id);
        ALTER TABLE documents DROP COLUMN owner_id;
        DROP TABLE users;
        """
    )
