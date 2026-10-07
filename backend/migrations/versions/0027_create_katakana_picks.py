"""create katakana_picks: which word each piece of a katakana token is

A token sung in katakana (アイタイ) is glossed as the words its hiragana
splits into, each spelled as its gloss guesses (会う). A pick is the user's
correction of that guess (合う), per token and piece, as a selected conflict
is for a reading. It can't be a conflict row: a token has one selected
conflict at most, and a katakana token can need a pick for each of its words.

`reading` is the piece's own when it was picked, so a pick is only applied
while the piece at that index still has it: a gloss built again can split
the katakana differently.

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-06 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0027"
down_revision: str | Sequence[str] | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        CREATE TABLE katakana_picks (
            -- Gone with its token, as when the lyrics are tokenized again.
            token_id INTEGER NOT NULL REFERENCES tokens (id) ON DELETE CASCADE,
            piece    SMALLINT NOT NULL,
            reading  TEXT NOT NULL,
            spelling TEXT NOT NULL,
            PRIMARY KEY (token_id, piece)
        );
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TABLE katakana_picks;")
