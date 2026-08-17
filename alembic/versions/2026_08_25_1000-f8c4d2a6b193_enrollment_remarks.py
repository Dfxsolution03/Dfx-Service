"""enrollment remarks

Phase 8 — adds scheme_enrollments.remarks (free-text operational note). Purely
additive, nullable; no existing column or financial data touched.

Revision ID: f8c4d2a6b193
Revises: e7b3c9a1d5f2
Create Date: 2026-08-25 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f8c4d2a6b193'
down_revision: Union[str, None] = 'e7b3c9a1d5f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("scheme_enrollments", sa.Column("remarks", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("scheme_enrollments", "remarks")
