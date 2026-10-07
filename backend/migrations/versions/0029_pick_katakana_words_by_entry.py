"""pick a katakana token's word by its JMDict entry, not its spelling

A pick named its word by spelling, which can't tell apart two entries with
the same reading written alike: two written in kana (うん, "yes" and
"some"), or two usually written with the same kanji (元 read もと). A pick
now names the entry, by idseq, and its spelling follows from it.

Each pick's entry is the first, in the order the words were offered, of
those read the piece's way and written as it was picked: the one whose
meaning the offer showed for that spelling. They were offered from the
gloss cache's row for the reading, so a pick is dropped, back to its
gloss's guess, only if that row has since been deleted.

Revision ID: 0029
Revises: 0028
Create Date: 2026-10-07 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0029"
down_revision: str | Sequence[str] | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The entries offered for katakana_picks row `kp`'s reading, as `e`, with
# each one's spelling as `spelling`: its usual kanji form (a form it marks
# common, or else its first), or its reading for an entry with none.
_OFFERED_ENTRIES = """
    FROM gloss_lookups gl
    CROSS JOIN jsonb_array_elements(gl.entries) WITH ORDINALITY AS e(entry, ord)
    CROSS JOIN LATERAL (
        SELECT COALESCE(
            (
                SELECT f.form ->> 'text'
                FROM jsonb_array_elements(e.entry -> 'kanji_forms')
                    WITH ORDINALITY AS f(form, ord)
                ORDER BY jsonb_array_length(f.form -> 'pri') = 0, f.ord
                LIMIT 1
            ),
            kp.reading
        ) AS spelling
    ) s
    WHERE gl.lookup_form = kp.reading AND gl.reading = kp.reading
      AND gl.source = 'jmdict'
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TABLE katakana_picks ADD COLUMN idseq INTEGER;")
    op.execute(
        f"""
        UPDATE katakana_picks kp SET idseq = (
            SELECT (e.entry ->> 'idseq')::int
            {_OFFERED_ENTRIES}
              AND s.spelling = kp.spelling
            ORDER BY e.ord
            LIMIT 1
        );
        """
    )
    op.execute("DELETE FROM katakana_picks WHERE idseq IS NULL;")
    op.execute(
        """
        ALTER TABLE katakana_picks
            ALTER COLUMN idseq SET NOT NULL,
            DROP COLUMN spelling;
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE katakana_picks ADD COLUMN spelling TEXT;")
    op.execute(
        f"""
        UPDATE katakana_picks kp SET spelling = (
            SELECT s.spelling
            {_OFFERED_ENTRIES}
              AND (e.entry ->> 'idseq')::int = kp.idseq
        );
        """
    )
    op.execute("DELETE FROM katakana_picks WHERE spelling IS NULL;")
    op.execute(
        """
        ALTER TABLE katakana_picks
            ALTER COLUMN spelling SET NOT NULL,
            DROP COLUMN idseq;
        """
    )
