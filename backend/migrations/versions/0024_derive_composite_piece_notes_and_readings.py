"""derive a composite piece's note and other readings when shown

A composite gloss's pieces stored the note a grammar word shows and the other
readings of their surface, worked out when the composite was cached, so a
changed heteronym rule or reworded grammar note never reached them. A piece
now stores the normalized form its note comes from and whether it flags other
readings, and both are worked out when it's shown, so every composite in the
old shape is dropped and its tokens unlinked, to be glossed again on the next
load.

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-05 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "0024"
down_revision: str | Sequence[str] | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COMPOSITES = "SELECT id FROM gloss_lookups WHERE source = 'composite'"


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    conn.execute(
        text(
            f"UPDATE tokens SET gloss_lookup_id = NULL WHERE gloss_lookup_id IN ({_COMPOSITES})"
        )
    )
    conn.execute(text(f"DELETE FROM gloss_lookups WHERE id IN ({_COMPOSITES})"))


def downgrade() -> None:
    """Downgrade schema."""
    # Nothing to restore: the rows were only a cache. Composites stored since
    # are in the new shape, which the old code can't read, so they're dropped
    # the same way.
    upgrade()
