"""tag colors reconciliation

Revision ID: 00ec5a9151da
Revises: 'c3a8f21b9e47'
Create Date: 2026-08-19 23:36:39.692617

Brings `products.tag_colors` under Alembic control.

Background: this column was added to the production database by hand, as an
emergency fix, without a matching alembic_version bump:

    ALTER TABLE products ADD COLUMN IF NOT EXISTS tag_colors VARCHAR(1000);

Production therefore already has the column while still stamped at
c3a8f21b9e47. This revision reconciles that: it is a no-op where the column
already exists, and creates it on a fresh database, so both follow one
identical migration history from here on.

Deliberately does NOT touch making_charge_discount_percent or
making_charge_discount_label — those are owned by c3a8f21b9e47 and re-adding
them would fail with 42701 duplicate_column.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '00ec5a9151da'
down_revision: Union[str, None] = 'c3a8f21b9e47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "products"
_COLUMN = "tag_colors"


def _has_column() -> bool:
    """Inspect the live schema rather than assuming what upgrade() will find.

    A dialect-agnostic check (works on PostgreSQL and SQLite alike), unlike
    `ADD COLUMN IF NOT EXISTS`, which SQLite does not support. It does require
    a real connection, so this revision cannot be rendered with `--sql`; that
    is already true of this lineage (f5c1d8a3e7b2 performs a live backfill).
    """
    return _COLUMN in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(_TABLE)}


def upgrade() -> None:
    if _has_column():
        # Production path: the emergency SQL already created it. Nothing to do
        # but let alembic_version advance past this revision.
        return
    op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(length=1000), nullable=True))


def downgrade() -> None:
    # NOTE: on the production database this column predates this revision (it
    # was created manually), so upgrade() was a no-op there. Downgrading past
    # this point therefore removes a column this revision did not create,
    # along with any data in it. Intentional for symmetry on fresh/dev
    # databases — be deliberate about running it against production.
    if _has_column():
        op.drop_column(_TABLE, _COLUMN)
