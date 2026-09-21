"""clear katakana glosses cached without their kanji

A katakana word's gloss now shows each word as it's usually written (心の声,
not こころのこえ), so the ones cached before are dropped and their tokens
unlinked, to be glossed again on the next load.

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-17 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# read_as was the key then marking a gloss of katakana looked up as hiragana
# (see app/katakana.py); 0015 clears what is left under it.
_KATAKANA_READING_GLOSSES = (
    "SELECT id FROM gloss_lookups WHERE source = 'composite' AND entries ? 'read_as'"
)


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        f"UPDATE tokens SET gloss_lookup_id = NULL WHERE gloss_lookup_id IN ({_KATAKANA_READING_GLOSSES});"
    )
    op.execute(f"DELETE FROM gloss_lookups WHERE id IN ({_KATAKANA_READING_GLOSSES});")


def downgrade() -> None:
    """Downgrade schema."""
    # Nothing to restore: the rows were only a cache.
