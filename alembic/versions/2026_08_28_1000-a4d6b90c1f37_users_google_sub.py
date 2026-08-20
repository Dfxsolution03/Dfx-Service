"""users.google_sub — link a verified Google account to a user

Revision ID: a4d6b90c1f37
Revises: '00ec5a9151da'
Create Date: 2026-08-28 10:00:00.000000

Adds the stable Google account identifier (the ID token's `sub` claim) to
`users`, so signing in with Google resolves to the *same* user across email
changes rather than being keyed on an address that can move.

Purely additive and nullable: every existing row keeps NULL, and NULLs are
distinct under a unique index on both PostgreSQL and SQLite, so any number of
never-linked users coexist. Nothing reads this column unless Google sign-in is
configured (see Settings.GOOGLE_OAUTH_CLIENT_IDS), so deploying this migration
ahead of that configuration changes no behaviour at all.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4d6b90c1f37'
down_revision: Union[str, None] = '00ec5a9151da'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "users"
_COLUMN = "google_sub"
_INDEX = "ix_users_google_sub"


def _has_column() -> bool:
    """Dialect-agnostic existence check — the same pattern 00ec5a9151da uses,
    and for the same reason: SQLite has no `ADD COLUMN IF NOT EXISTS`, and this
    lineage already requires a live connection (so `--sql` rendering is out)."""
    return _COLUMN in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(_TABLE)}


def upgrade() -> None:
    if _has_column():
        return
    op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(length=255), nullable=True))
    # Unique, not merely indexed: one Google account must never end up mapped
    # onto two users. This is also what makes the concurrent-first-sign-in race
    # in AuthService._register_google_customer resolvable — the loser of the
    # race gets an IntegrityError and adopts the winner's row.
    op.create_index(_INDEX, _TABLE, [_COLUMN], unique=True)


def downgrade() -> None:
    if _has_column():
        op.drop_index(_INDEX, table_name=_TABLE)
        op.drop_column(_TABLE, _COLUMN)
