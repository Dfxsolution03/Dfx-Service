"""inventory_items.catalogue_product_id — Product(1)->InventoryItem(many) link

Revision ID: e1a3c5d7f9b2
Revises: d9f1b3c5e7a2
Create Date: 2026-09-10 10:00:00

Phase 11 — a catalogue Product may represent several physical pieces. This adds
the MANY side: inventory_items.catalogue_product_id -> products.id
(NULLABLE, ON DELETE SET NULL, indexed).

Additive and reversible. It is BACKFILLED from the existing 1:1 relationship
(Product.inventory_item_id) so every already-published item ends up pointing at
the product it was published from — no existing link is lost and no product/
inventory/sale/quotation row is created, deleted, or otherwise altered. The
legacy Product.inventory_item_id column is KEPT (marks the listing's ORIGIN
item); this new column is purely additive.

Tenant safety: the backfill joins on (products.inventory_item_id == id) AND
(products.tenant_id == inventory_items.tenant_id), so an item can only ever be
linked to a product in its OWN tenant.
"""
from alembic import op
import sqlalchemy as sa


revision = "e1a3c5d7f9b2"
down_revision = "d9f1b3c5e7a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "inventory_items",
        sa.Column("catalogue_product_id", sa.String(length=50), nullable=True),
    )
    op.create_index(
        "ix_inventory_items_catalogue_product_id",
        "inventory_items",
        ["catalogue_product_id"],
    )
    op.create_foreign_key(
        "fk_inventory_items_catalogue_product_id",
        "inventory_items",
        "products",
        ["catalogue_product_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Backfill from the existing 1:1 link, tenant-scoped. Idempotent: only fills
    # rows still NULL, only where a matching same-tenant product exists.
    op.execute(
        """
        UPDATE inventory_items AS ii
        SET catalogue_product_id = p.id
        FROM products AS p
        WHERE p.inventory_item_id = ii.id
          AND p.tenant_id = ii.tenant_id
          AND ii.catalogue_product_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_inventory_items_catalogue_product_id", "inventory_items", type_="foreignkey"
    )
    op.drop_index("ix_inventory_items_catalogue_product_id", table_name="inventory_items")
    op.drop_column("inventory_items", "catalogue_product_id")
