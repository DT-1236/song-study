"""rename gloss_lookups.dictionary_form to lookup_form

Gloss lookups are now always keyed off the token's normalized_form (not
dictionary_form) — see app/glosses.py for why. The column no longer holds a
Sudachi dictionary_form specifically, so give it a form-agnostic name.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-07 09:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "ALTER TABLE gloss_lookups RENAME COLUMN dictionary_form TO lookup_form;"
    )
    op.execute(
        """
        ALTER TABLE gloss_lookups
            RENAME CONSTRAINT gloss_lookups_dictionary_form_reading_key
            TO gloss_lookups_lookup_form_reading_key;
        """
    )
    # Stale under the old (dictionary_form, reading) keying scheme.
    op.execute("TRUNCATE gloss_lookups CASCADE;")
    op.execute("UPDATE tokens SET gloss_lookup_id = NULL;")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        """
        ALTER TABLE gloss_lookups
            RENAME CONSTRAINT gloss_lookups_lookup_form_reading_key
            TO gloss_lookups_dictionary_form_reading_key;
        """
    )
    op.execute(
        "ALTER TABLE gloss_lookups RENAME COLUMN lookup_form TO dictionary_form;"
    )
