"""create gloss_lookups table

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-05 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        CREATE TABLE gloss_lookups (
            id               SERIAL PRIMARY KEY,
            dictionary_form  TEXT NOT NULL,
            reading          TEXT NOT NULL,          -- hiragana, matches JMDict's own convention

            entries          JSONB NOT NULL,          -- JMDict entries filtered to this reading; [] if none found

            fetched_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

            UNIQUE (dictionary_form, reading)
        );
        """
    )
    op.execute(
        """
        ALTER TABLE tokens
            ADD COLUMN gloss_lookup_id INT REFERENCES gloss_lookups (id);
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE tokens DROP COLUMN gloss_lookup_id;")
    op.execute("DROP TABLE gloss_lookups;")
