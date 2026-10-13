"""record when a document's processing finished

A document is processed once a job has finished with its text, not once it
has tokens: an empty text, or one that yields no tokens, never has any, so
"has tokens" would start a job for it on every poll.

Revision ID: 0035
Revises: 0034
Create Date: 2026-10-13 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0035"
down_revision: str | Sequence[str] | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        ALTER TABLE documents ADD COLUMN processed_at TIMESTAMPTZ;

        UPDATE documents SET processed_at = now()
        WHERE EXISTS (SELECT 1 FROM tokens WHERE document_id = documents.id);

        CREATE OR REPLACE FUNCTION reset_document_processing() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            DELETE FROM tokens WHERE document_id = NEW.id;
            -- A job processing the old text finds its claim gone and writes
            -- nothing, and the next request starts the new text.
            NEW.processing_started_at := NULL;
            NEW.processing_failed := FALSE;
            NEW.processed_at := NULL;
            RETURN NEW;
        END;
        $$;
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        """
        CREATE OR REPLACE FUNCTION reset_document_processing() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            DELETE FROM tokens WHERE document_id = NEW.id;
            -- A job processing the old text finds its claim gone and writes
            -- nothing, and the next request starts the new text.
            NEW.processing_started_at := NULL;
            NEW.processing_failed := FALSE;
            RETURN NEW;
        END;
        $$;

        ALTER TABLE documents DROP COLUMN processed_at;
        """
    )
