"""quotations table (Phase 4 — sample bill that does not sell)

Revision ID: d5f7a1c3e9b4
Revises: c4e6f8a0b2d1
Create Date: 2026-09-01 10:00:00

Phase 4 — Billing. Additive only, fully reversible: one NEW table `quotations`
holding a computed, non-selling bill snapshot. No existing table/column is
altered or dropped, and no data is backfilled. A quotation never marks an
inventory item SOLD and never spends a scheme balance (see the model docstring).
"""
from alembic import op
import sqlalchemy as sa


revision = "d5f7a1c3e9b4"
down_revision = "c4e6f8a0b2d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quotations",
        sa.Column("id", sa.String(length=50), nullable=False),
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column("quotation_number", sa.String(length=30), nullable=False),
        sa.Column("inventory_item_id", sa.String(length=50), nullable=True),
        sa.Column("product_code", sa.String(length=50), nullable=False),
        sa.Column("product_name", sa.String(length=200), nullable=False),
        sa.Column("customer_id", sa.String(length=50), nullable=True),
        sa.Column("customer_name", sa.String(length=150), nullable=True),
        sa.Column("customer_phone", sa.String(length=20), nullable=True),
        sa.Column("gst_applied", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("final_amount", sa.Float(), nullable=False),
        sa.Column("scheme_amount_total", sa.Float(), server_default=sa.text("0"), nullable=False),
        sa.Column("outstanding_amount", sa.Float(), nullable=False),
        sa.Column("breakdown_json", sa.JSON(), nullable=False),
        sa.Column("scheme_breakdown_json", sa.JSON(), nullable=True),
        sa.Column("estimated_gross_margin", sa.Float(), nullable=True),
        sa.Column("profit_or_loss_label", sa.String(length=20), nullable=True),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("created_by", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["inventory_item_id"], ["inventory_items.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["customer_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "quotation_number", name="uq_quotations_tenant_number"),
    )
    op.create_index(op.f("ix_quotations_tenant_id"), "quotations", ["tenant_id"], unique=False)
    op.create_index(
        op.f("ix_quotations_inventory_item_id"), "quotations", ["inventory_item_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_quotations_inventory_item_id"), table_name="quotations")
    op.drop_index(op.f("ix_quotations_tenant_id"), table_name="quotations")
    op.drop_table("quotations")
