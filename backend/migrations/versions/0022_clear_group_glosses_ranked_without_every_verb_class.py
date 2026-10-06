"""clear group glosses ranked without every verb class

Sense ranking now counts every JMDict tag naming a verb as one, so a sense
tagged only with its class (する's "to do", tagged "suru verb - included")
no longer ranks last. A word's own gloss is ranked when it's shown, but a
group's pieces were ranked when the group was cached, so the groups with a
piece tagged with one of those classes are dropped and their tokens
unlinked, to be glossed again on the next load.

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-05 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "0022"
down_revision: str | Sequence[str] | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Patterns for the tags that count as a verb's now and didn't before, as of
# this migration: app.glosses then listed the Godan classes ending in く, む,
# る, す and う, Iku/Yuku, Ichidan, Kuru, and transitivity, and now takes
# every tag naming a verb.
_NEWLY_VERB_PATTERNS = [
    *(
        f'%"{tag}"%'
        for tag in (
            "Godan verb - -aru special class",
            "Godan verb with 'bu' ending",
            "Godan verb with 'gu' ending",
            "Godan verb with 'nu' ending",
            "Godan verb with 'ru' ending (irregular verb)",
            "Godan verb with 'tsu' ending",
            "Godan verb with 'u' ending (special class)",
            "Ichidan verb - kureru special class",
            "Ichidan verb - zuru verb (alternative form of -jiru verbs)",
            "irregular nu verb",
            "irregular ru verb, plain form ends with -ri",
            "su verb - precursor to the modern suru",
            "suru verb - included",
            "suru verb - special class",
            "verb unspecified",
        )
    ),
    '%"Nidan verb %',
    '%"Yodan verb %',
]

# A piece's senses are stored with their tags, so the entries' JSON text
# holds a tag exactly when some piece's sense has it.
_STALE_GLOSSES = """
    SELECT id FROM gloss_lookups
    WHERE source = 'composite'
      AND CAST(entries AS TEXT) LIKE ANY (CAST(:patterns AS TEXT[]))
"""


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    patterns = {"patterns": _NEWLY_VERB_PATTERNS}
    conn.execute(
        text(
            f"UPDATE tokens SET gloss_lookup_id = NULL WHERE gloss_lookup_id IN ({_STALE_GLOSSES})"
        ),
        patterns,
    )
    conn.execute(
        text(f"DELETE FROM gloss_lookups WHERE id IN ({_STALE_GLOSSES})"), patterns
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Nothing to restore: the rows were only a cache.
