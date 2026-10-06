"""refer composite pieces to their lookups

A composite gloss's pieces used to hold copies of their lookups' senses,
already ranked, so each change to ranking or to what a lookup returns needed
a migration of its own to clear the composites it touched (0013, 0015, 0019,
0022). Each piece now holds the key of the lookup it's glossed from and the
part of speech to rank it for, and is resolved and ranked when shown, so
every composite in the old shape is dropped and its tokens unlinked, to be
glossed again on the next load.

From here, a ranking change needs no migration, and a change to what a
lookup returns needs only that lookup's rows dropped: a piece whose lookup
isn't cached is looked up again when shown. Only a change to a composite's
own structure (how a word splits into pieces, or which key a piece is
glossed under) still means clearing composites.

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-05 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "0023"
down_revision: str | Sequence[str] | None = "0022"
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
