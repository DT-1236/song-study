"""reset a document's processing when its text changes

Everything processing derived from a document's text — its tokens, their
conflicts, a job's claim and a recorded failure — is dropped by a trigger
on the text itself, so no path that writes the text can leave the old
text's tokens behind.

Revision ID: 0034
Revises: 0033
Create Date: 2026-10-13 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0034"
down_revision: str | Sequence[str] | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        CREATE FUNCTION reset_document_processing() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            -- Conflicts first: their foreign key to tokens doesn't cascade.
            DELETE FROM conflicts
            WHERE token_id IN (SELECT id FROM tokens WHERE document_id = NEW.id);
            DELETE FROM tokens WHERE document_id = NEW.id;
            -- A job processing the old text finds its claim gone and writes
            -- nothing, and the next request starts the new text.
            NEW.processing_started_at := NULL;
            NEW.processing_failed := FALSE;
            RETURN NEW;
        END;
        $$;

        CREATE TRIGGER reset_document_processing
        BEFORE UPDATE OF text ON documents
        FOR EACH ROW
        WHEN (OLD.text IS DISTINCT FROM NEW.text)
        EXECUTE FUNCTION reset_document_processing();
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        """
        DROP TRIGGER reset_document_processing ON documents;
        DROP FUNCTION reset_document_processing();
        """
    )
