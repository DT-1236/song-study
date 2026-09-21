"""add users' Google identity

google_sub is the stable id Google gives an account, which the login flow
finds or creates a user by. It's NULL for the seeded default user, which
nobody logs in as.

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-18 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0017"
down_revision: str | Sequence[str] | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "ALTER TABLE users ADD COLUMN google_sub TEXT UNIQUE, ADD COLUMN email TEXT;"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE users DROP COLUMN email, DROP COLUMN google_sub;")
