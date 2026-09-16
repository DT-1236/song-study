"""add phrase_start_position to tokens

Marks a token as part of a multi-token JMDict match: the run of consecutive
tokens sharing the same phrase_start_position (the `position` of the first
token in the run) combine into one headword this app's tokenizer wouldn't
otherwise look up as a single unit (e.g. この/期/に/及ん/で -> この期に及んで).
NULL for a token that wasn't merged with its neighbors. See
app/phrase_merge.py for how it's computed; every merged token also gets the
phrase's own gloss_lookup_id, so this column is purely for the frontend to
know which tokens to render/click as one span.

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0012'
down_revision: Union[str, Sequence[str], None] = '0011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TABLE tokens ADD COLUMN phrase_start_position INT;")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE tokens DROP COLUMN phrase_start_position;")
