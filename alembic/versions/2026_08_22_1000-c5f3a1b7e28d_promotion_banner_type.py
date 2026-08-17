"""promotion banner_type (STANDARD / IMAGE_ONLY)

Adds promotions.banner_type. Purely additive, NOT NULL with server_default
'STANDARD' so every existing promotion becomes a STANDARD banner and all
current API consumers keep working unchanged.

Revision ID: c5f3a1b7e28d
Revises: b4e2d9f16c33
Create Date: 2026-08-22 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c5f3a1b7e28d'
down_revision: Union[str, None] = 'b4e2d9f16c33'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "promotions",
        sa.Column("banner_type", sa.String(length=20), server_default="STANDARD", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("promotions", "banner_type")
