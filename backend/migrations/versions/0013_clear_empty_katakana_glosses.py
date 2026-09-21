"""clear cached empty glosses of katakana words

Katakana with no JMDict entry of its own is now glossed as hiragana (see
app/katakana.py), but its empty result from before is cached. Its tokens are
unlinked so the next load glosses them again.

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-16 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: Union[str, Sequence[str], None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Matches app.katakana.is_katakana_word.
_EMPTY_KATAKANA_GLOSSES = """
    SELECT id FROM gloss_lookups
    WHERE source = 'jmdict' AND entries = CAST('[]' AS JSONB) AND lookup_form ~ '^[ァ-ヶー]{2,}$'
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        f"UPDATE tokens SET gloss_lookup_id = NULL WHERE gloss_lookup_id IN ({_EMPTY_KATAKANA_GLOSSES});"
    )
    op.execute(f"DELETE FROM gloss_lookups WHERE id IN ({_EMPTY_KATAKANA_GLOSSES});")


def downgrade() -> None:
    """Downgrade schema."""
    # Nothing to restore: the rows were only a cache.
    pass
