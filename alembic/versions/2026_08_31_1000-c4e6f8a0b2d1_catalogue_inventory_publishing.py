"""catalogue sub_category + inventory→catalogue publishing link/pricing

Revision ID: c4e6f8a0b2d1
Revises: b2d4e6f8a0c1
Create Date: 2026-08-31 10:00:00

Phase 3 — Catalogue & Inventory. Additive only, fully reversible:
  * products gains: sub_category, inventory_item_id (FK→inventory_items,
    ON DELETE SET NULL, UNIQUE per (tenant_id, inventory_item_id) so a single
    inventory item maps to at most one catalogue product and duplicate
    publishing is blocked; NULLs are distinct so standalone manual products are
    unaffected), pricing_source, computed_selling_cost, price_effective_date.
  * inventory_items gains: add_to_catalogue (bool, default false).

All columns are NULLABLE (or defaulted), no existing column is altered or
dropped, and no data is backfilled — existing catalogue products and inventory
items keep working unchanged.
"""
from alembic import op
import sqlalchemy as sa


revision = "c4e6f8a0b2d1"
down_revision = "b2d4e6f8a0c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("products", sa.Column("sub_category", sa.String(length=100), nullable=True))
    op.add_column("products", sa.Column("inventory_item_id", sa.String(length=50), nullable=True))
    op.add_column("products", sa.Column("pricing_source", sa.String(length=20), nullable=True))
    op.add_column("products", sa.Column("computed_selling_cost", sa.Float(), nullable=True))
    op.add_column("products", sa.Column("price_effective_date", sa.Date(), nullable=True))
    op.create_index(
        op.f("ix_products_inventory_item_id"), "products", ["inventory_item_id"], unique=False
    )
    op.create_unique_constraint(
        "uq_products_tenant_inventory_item", "products", ["tenant_id", "inventory_item_id"]
    )
    op.create_foreign_key(
        "fk_products_inventory_item_id",
        "products", "inventory_items",
        ["inventory_item_id"], ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "inventory_items",
        sa.Column("add_to_catalogue", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_index(
        op.f("ix_inventory_items_add_to_catalogue"), "inventory_items", ["add_to_catalogue"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_inventory_items_add_to_catalogue"), table_name="inventory_items")
    op.drop_column("inventory_items", "add_to_catalogue")

    op.drop_constraint("fk_products_inventory_item_id", "products", type_="foreignkey")
    op.drop_constraint("uq_products_tenant_inventory_item", "products", type_="unique")
    op.drop_index(op.f("ix_products_inventory_item_id"), table_name="products")
    op.drop_column("products", "price_effective_date")
    op.drop_column("products", "computed_selling_cost")
    op.drop_column("products", "pricing_source")
    op.drop_column("products", "inventory_item_id")
    op.drop_column("products", "sub_category")
