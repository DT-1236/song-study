"""relink English words by their surface

An English word is now glossed under how it's written rather than Sudachi's
normalized form, which is katakana for many (How -> ハウ) and got a JMDict
gloss. Its tokens outside groups are unlinked, to be glossed again on the
next load.

Revision ID: 0039
Revises: 0038
Create Date: 2026-10-20 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0039"
down_revision: str | Sequence[str] | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # The surface test matches app.glosses.is_probably_english. A token
    # already linked under its surface is left alone.
    op.execute(
        """
        UPDATE tokens t SET gloss_lookup_id = NULL
        FROM gloss_lookups gl
        WHERE gl.id = t.gloss_lookup_id
          AND t.phrase_start_position IS NULL
          AND t.surface ~ '[A-Za-z]' AND t.surface !~ '[ぁ-んァ-ヶー一-龥]'
          AND gl.lookup_form <> t.surface
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Nothing to restore: the links are rebuilt from the tokens.
