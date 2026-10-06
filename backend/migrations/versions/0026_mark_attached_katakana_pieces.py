"""mark which katakana pieces are attached to a word

A katakana word's pieces now record whether each is grammar attached to a
word, rather than leaving the card rule to infer it from its unit's size. The
ones cached before are dropped and their tokens unlinked, to be glossed again
on the next load.

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-06 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "0026"
down_revision: str | Sequence[str] | None = "0025"
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
