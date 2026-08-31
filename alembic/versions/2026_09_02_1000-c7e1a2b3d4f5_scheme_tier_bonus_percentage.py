"""per-tier bonus_percentage on scheme_tiers

Revision ID: c7e1a2b3d4f5
Revises: b2d4e6f8a0c1
Create Date: 2026-09-02 10:00:00

Additive only, fully reversible: scheme_tiers gains one NOT NULL column
bonus_percentage (Float, server_default 0) holding the per-tier bonus as a
percentage of base maturity. Existing rows backfill to 0 via the server default
(= no bonus, preserving current behaviour). Maturity figures (base/bonus/final)
stay derived in the response layer and are never stored.
"""
from alembic import op
import sqlalchemy as sa


revision = "c7e1a2b3d4f5"
down_revision = "b2d4e6f8a0c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scheme_tiers",
        sa.Column("bonus_percentage", sa.Float(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("scheme_tiers", "bonus_percentage")
