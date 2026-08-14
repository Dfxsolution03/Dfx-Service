"""scheme closure and redemption toward jewellery sales

Revision ID: e4a7c2b9d6f1
Revises: d9f3a7c5b1e8
Create Date: 2026-08-18 10:00:00.000000

Lets a customer's accumulated scheme balance settle a jewellery invoice. Adds:

  - scheme_enrollments.closed_at / closed_by / closure_reason
        Closure was previously unrecordable — only a status string flipped, with
        no audit of when, who, or why. All nullable; existing rows keep NULL.
  - scheme_redemptions
        One immutable row per application of scheme balance to a sale. Needed
        for the scheme-side audit chain (enrollment -> payments -> redemption ->
        sale -> invoice) and to support several partial redemptions against one
        enrollment.
  - sale_payments.enrollment_id
        Nullable FK. Set ONLY on source=SCHEME_REDEMPTION rows. Without it a
        redemption row cannot say which scheme was drawn down, so neither the
        double-use guard nor the "redemption is not cash" split is possible.
        NULL on every ordinary collection and every refund.

No monetary cache is added anywhere. The eligible balance is always derived as
SUM(successful scheme payments) - SUM(scheme_redemptions), so there is nothing
to drift out of sync.

No existing column is altered and no historical row is rewritten. Enrollment
statuses gain CLOSED and REDEEMED at the application level (status is free text
in the DB); COMPLETED keeps its existing maturity meaning. No redemption rows
are fabricated for existing data — a redemption exists only where an Admin
actually performed one.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e4a7c2b9d6f1'
down_revision: Union[str, None] = 'd9f3a7c5b1e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("scheme_enrollments", sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("scheme_enrollments", sa.Column("closed_by", sa.String(length=50), nullable=True))
    op.add_column("scheme_enrollments", sa.Column("closure_reason", sa.String(length=500), nullable=True))
    op.create_foreign_key(
        "fk_scheme_enrollments_closed_by_users", "scheme_enrollments", "users",
        ["closed_by"], ["id"], ondelete="SET NULL",
    )

    op.create_table(
        "scheme_redemptions",
        sa.Column("id", sa.String(length=50), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column("enrollment_id", sa.String(length=50), nullable=False),
        sa.Column("customer_id", sa.String(length=50), nullable=False),
        sa.Column("sale_id", sa.String(length=50), nullable=False),
        sa.Column("invoice_number", sa.String(length=30), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_by", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["enrollment_id"], ["scheme_enrollments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["customer_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sale_id"], ["sales.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["recorded_by"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_scheme_redemptions_tenant_id", "scheme_redemptions", ["tenant_id"])
    op.create_index("ix_scheme_redemptions_enrollment_id", "scheme_redemptions", ["enrollment_id"])
    op.create_index("ix_scheme_redemptions_customer_id", "scheme_redemptions", ["customer_id"])
    op.create_index("ix_scheme_redemptions_sale_id", "scheme_redemptions", ["sale_id"])

    op.add_column("sale_payments", sa.Column("enrollment_id", sa.String(length=50), nullable=True))
    op.create_index("ix_sale_payments_enrollment_id", "sale_payments", ["enrollment_id"])
    op.create_foreign_key(
        "fk_sale_payments_enrollment_id", "sale_payments", "scheme_enrollments",
        ["enrollment_id"], ["id"], ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("fk_sale_payments_enrollment_id", "sale_payments", type_="foreignkey")
    op.drop_index("ix_sale_payments_enrollment_id", table_name="sale_payments")
    op.drop_column("sale_payments", "enrollment_id")

    op.drop_index("ix_scheme_redemptions_sale_id", table_name="scheme_redemptions")
    op.drop_index("ix_scheme_redemptions_customer_id", table_name="scheme_redemptions")
    op.drop_index("ix_scheme_redemptions_enrollment_id", table_name="scheme_redemptions")
    op.drop_index("ix_scheme_redemptions_tenant_id", table_name="scheme_redemptions")
    op.drop_table("scheme_redemptions")

    op.drop_constraint("fk_scheme_enrollments_closed_by_users", "scheme_enrollments", type_="foreignkey")
    op.drop_column("scheme_enrollments", "closure_reason")
    op.drop_column("scheme_enrollments", "closed_by")
    op.drop_column("scheme_enrollments", "closed_at")
