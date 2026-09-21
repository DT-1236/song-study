"""clear katakana glosses cached under the old key

The hiragana a katakana word was looked up as is now stored as looked_up_as
rather than read_as, so the glosses cached under the old key are dropped and
their tokens unlinked, to be glossed again on the next load.

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-17 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_KEY_GLOSSES = (
    "SELECT id FROM gloss_lookups WHERE source = 'composite' AND entries ? 'read_as'"
)


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        f"UPDATE tokens SET gloss_lookup_id = NULL WHERE gloss_lookup_id IN ({_OLD_KEY_GLOSSES});"
    )
    op.execute(f"DELETE FROM gloss_lookups WHERE id IN ({_OLD_KEY_GLOSSES});")


def downgrade() -> None:
    """Downgrade schema."""
    # Nothing to restore: the rows were only a cache.
