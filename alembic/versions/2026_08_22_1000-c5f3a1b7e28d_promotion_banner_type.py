"""promotion banner_type (STANDARD / IMAGE_ONLY)

Adds promotions.banner_type. Purely additive, NOT NULL with server_default
'STANDARD' so every existing promotion becomes a STANDARD banner and all
current API consumers keep working unchanged.

Revision ID: c5f3a1b7e28d
Revises: f5c1d8a3e7b2
Create Date: 2026-08-22 10:00:00.000000

Deployment note: this promotion-only deployment branch re-parents the migration
directly onto the production head f5c1d8a3e7b2 (Phase 1). Phase 2/3 migrations
are intentionally absent here, so the chain is f5c1d8a3e7b2 -> c5f3a1b7e28d with
no gap. The column added is additive and independent of Phase 2/3.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c5f3a1b7e28d'
down_revision: Union[str, None] = 'f5c1d8a3e7b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "promotions",
        sa.Column("banner_type", sa.String(length=20), server_default="STANDARD", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("promotions", "banner_type")
