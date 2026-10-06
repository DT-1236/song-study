"""place a katakana word's pieces within its token

A katakana word's gloss (see app/katakana.py) now stores where in the
katakana each of its pieces is, and which of the hiragana's words it came
from, so a line sung in katakana can point at each word's card. The ones
cached before are dropped and their tokens unlinked, to be glossed again on
the next load.

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-05 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "0025"
down_revision: str | Sequence[str] | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KATAKANA_GLOSSES = (
    "SELECT id FROM gloss_lookups"
    " WHERE source = 'composite' AND entries ? 'looked_up_as'"
)


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    conn.execute(
        text(
            f"UPDATE tokens SET gloss_lookup_id = NULL WHERE gloss_lookup_id IN ({_KATAKANA_GLOSSES})"
        )
    )
    conn.execute(text(f"DELETE FROM gloss_lookups WHERE id IN ({_KATAKANA_GLOSSES})"))


def downgrade() -> None:
    """Downgrade schema."""
    # Nothing to restore: the rows were only a cache, and the old code reads
    # the new shape, ignoring what it adds.
