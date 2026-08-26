"""users.date_of_birth (customer DOB)

Revision ID: a1c2d3e4f5a6
Revises: c3a8f21b9e47
Create Date: 2026-08-29 10:00:00

Additive only: one nullable DATE column on `users` for customer date of birth.
DATE (not timestamp) — a birthday is a calendar date with no time/zone. Nullable
because existing rows and every non-Customer user legitimately have none; the
"required for new customers" rule is enforced at the API layer, not the column.
No existing table is altered/dropped, no data backfilled. Fully reversible.
"""
from alembic import op
import sqlalchemy as sa


revision = "a1c2d3e4f5a6"
down_revision = "c3a8f21b9e47"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("date_of_birth", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "date_of_birth")
