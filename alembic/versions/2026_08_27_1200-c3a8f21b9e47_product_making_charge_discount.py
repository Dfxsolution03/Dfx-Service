"""product making-charge discount fields (catalogue reconcile)

Revision ID: c3a8f21b9e47
Revises: bd7c9e1a4f26
Create Date: 2026-08-27 12:00:00

Additive only: two nullable columns on `products`, ported from the remote
catalogue snapshot so the customer catalogue API can expose the discount label
the mobile app reads. No existing table is altered/dropped, no data backfilled.
Fully reversible. tag_colors from the remote snapshot is intentionally not added
(no client consumes it).
"""
from alembic import op
import sqlalchemy as sa


revision = "c3a8f21b9e47"
down_revision = "bd7c9e1a4f26"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("products", sa.Column("making_charge_discount_percent", sa.Float(), nullable=True))
    op.add_column("products", sa.Column("making_charge_discount_label", sa.String(length=200), nullable=True))


def downgrade() -> None:
    op.drop_column("products", "making_charge_discount_label")
    op.drop_column("products", "making_charge_discount_percent")
