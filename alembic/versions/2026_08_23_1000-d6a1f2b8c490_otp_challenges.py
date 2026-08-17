"""otp challenges (customer-app redemption OTP)

Phase 5 — adds otp_challenges for single-use, expiring, attempt-limited
verification codes delivered to the customer app (IN_APP). Purely additive: one
new table, no existing table touched.

Revision ID: d6a1f2b8c490
Revises: c5f3a1b7e28d
Create Date: 2026-08-23 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd6a1f2b8c490'
down_revision: Union[str, None] = 'c5f3a1b7e28d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "otp_challenges",
        sa.Column("id", sa.String(length=50), nullable=False),
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column("customer_id", sa.String(length=50), nullable=False),
        sa.Column("purpose", sa.String(length=30), nullable=False),
        sa.Column("sale_id", sa.String(length=50), nullable=True),
        sa.Column("code_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="5", nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sale_id"], ["sales.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_otp_challenges_tenant_id"), "otp_challenges", ["tenant_id"])
    op.create_index(op.f("ix_otp_challenges_customer_id"), "otp_challenges", ["customer_id"])
    op.create_index(op.f("ix_otp_challenges_sale_id"), "otp_challenges", ["sale_id"])
    op.create_index("ix_otp_active_lookup", "otp_challenges", ["tenant_id", "customer_id", "purpose", "sale_id"])


def downgrade() -> None:
    op.drop_index("ix_otp_active_lookup", table_name="otp_challenges")
    op.drop_index(op.f("ix_otp_challenges_sale_id"), table_name="otp_challenges")
    op.drop_index(op.f("ix_otp_challenges_customer_id"), table_name="otp_challenges")
    op.drop_index(op.f("ix_otp_challenges_tenant_id"), table_name="otp_challenges")
    op.drop_table("otp_challenges")
