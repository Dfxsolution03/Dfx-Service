"""billing system inventory and sales

Revision ID: c3f7a1e9d4b2
Revises: 9b75ac483d2f
Create Date: 2026-08-12 10:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3f7a1e9d4b2'
down_revision: Union[str, None] = '9b75ac483d2f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'inventory_items',
        sa.Column('id', sa.String(length=50), nullable=False),
        sa.Column('tenant_id', sa.String(length=50), nullable=False),
        sa.Column('product_code', sa.String(length=50), nullable=False),
        sa.Column('product_name', sa.String(length=200), nullable=False),
        sa.Column('category', sa.String(length=100), nullable=True),
        sa.Column('subcategory', sa.String(length=100), nullable=True),
        sa.Column('huid', sa.String(length=20), nullable=True),
        sa.Column('purity', sa.String(length=10), nullable=False),
        sa.Column('gross_weight_grams', sa.Float(), nullable=False),
        sa.Column('net_gold_weight_grams', sa.Float(), nullable=False),
        sa.Column('vendor_name', sa.String(length=200), nullable=True),
        sa.Column('purchase_date', sa.Date(), nullable=True),
        sa.Column('purchase_invoice_ref', sa.String(length=100), nullable=True),
        sa.Column('purchase_cost', sa.Float(), nullable=True),
        sa.Column('image_storage_path', sa.String(length=500), nullable=True),
        sa.Column('stock_status', sa.String(length=20), nullable=False),
        sa.Column('making_charge_type', sa.String(length=20), nullable=False),
        sa.Column('making_charge_value', sa.Float(), nullable=False),
        sa.Column('wastage_type', sa.String(length=20), nullable=False),
        sa.Column('wastage_value', sa.Float(), nullable=False),
        sa.Column('stone_charge_amount', sa.Float(), nullable=False),
        sa.Column('other_charges_amount', sa.Float(), nullable=False),
        sa.Column('tax_rate_percent', sa.Float(), nullable=False),
        sa.Column('created_by', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'product_code', name='uq_inventory_items_tenant_product_code'),
    )
    op.create_index(op.f('ix_inventory_items_tenant_id'), 'inventory_items', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_inventory_items_product_code'), 'inventory_items', ['product_code'], unique=False)
    op.create_index(op.f('ix_inventory_items_stock_status'), 'inventory_items', ['stock_status'], unique=False)

    op.create_table(
        'sales',
        sa.Column('id', sa.String(length=50), nullable=False),
        sa.Column('tenant_id', sa.String(length=50), nullable=False),
        sa.Column('invoice_number', sa.String(length=30), nullable=False),
        sa.Column('inventory_item_id', sa.String(length=50), nullable=False),
        sa.Column('customer_id', sa.String(length=50), nullable=True),
        sa.Column('customer_name', sa.String(length=150), nullable=True),
        sa.Column('customer_phone', sa.String(length=20), nullable=True),
        sa.Column('product_code', sa.String(length=50), nullable=False),
        sa.Column('product_name', sa.String(length=200), nullable=False),
        sa.Column('huid', sa.String(length=20), nullable=True),
        sa.Column('purity', sa.String(length=10), nullable=False),
        sa.Column('gross_weight_grams', sa.Float(), nullable=False),
        sa.Column('net_gold_weight_grams', sa.Float(), nullable=False),
        sa.Column('gold_rate_24k', sa.Float(), nullable=False),
        sa.Column('gold_rate_purity_factor', sa.Float(), nullable=False),
        sa.Column('gold_rate_applied', sa.Float(), nullable=False),
        sa.Column('gold_rate_source', sa.String(length=50), nullable=False),
        sa.Column('gold_rate_effective_date', sa.Date(), nullable=False),
        sa.Column('gold_value_amount', sa.Float(), nullable=False),
        sa.Column('making_charge_type', sa.String(length=20), nullable=False),
        sa.Column('making_charge_value', sa.Float(), nullable=False),
        sa.Column('making_charge_amount', sa.Float(), nullable=False),
        sa.Column('wastage_type', sa.String(length=20), nullable=False),
        sa.Column('wastage_value', sa.Float(), nullable=False),
        sa.Column('wastage_amount', sa.Float(), nullable=False),
        sa.Column('stone_charge_amount', sa.Float(), nullable=False),
        sa.Column('other_charges_amount', sa.Float(), nullable=False),
        sa.Column('subtotal_before_tax', sa.Float(), nullable=False),
        sa.Column('tax_rate_percent', sa.Float(), nullable=False),
        sa.Column('tax_amount', sa.Float(), nullable=False),
        sa.Column('discount_amount', sa.Float(), nullable=False),
        sa.Column('final_amount', sa.Float(), nullable=False),
        sa.Column('purchase_cost_snapshot', sa.Float(), nullable=True),
        sa.Column('estimated_gross_margin', sa.Float(), nullable=True),
        sa.Column('sale_timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_by', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['inventory_item_id'], ['inventory_items.id']),
        sa.ForeignKeyConstraint(['customer_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'invoice_number', name='uq_sales_tenant_invoice_number'),
    )
    op.create_index(op.f('ix_sales_tenant_id'), 'sales', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_sales_invoice_number'), 'sales', ['invoice_number'], unique=False)
    op.create_index(op.f('ix_sales_inventory_item_id'), 'sales', ['inventory_item_id'], unique=False)
    op.create_index(op.f('ix_sales_customer_id'), 'sales', ['customer_id'], unique=False)
    op.create_index(op.f('ix_sales_product_code'), 'sales', ['product_code'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_sales_product_code'), table_name='sales')
    op.drop_index(op.f('ix_sales_customer_id'), table_name='sales')
    op.drop_index(op.f('ix_sales_inventory_item_id'), table_name='sales')
    op.drop_index(op.f('ix_sales_invoice_number'), table_name='sales')
    op.drop_index(op.f('ix_sales_tenant_id'), table_name='sales')
    op.drop_table('sales')

    op.drop_index(op.f('ix_inventory_items_stock_status'), table_name='inventory_items')
    op.drop_index(op.f('ix_inventory_items_product_code'), table_name='inventory_items')
    op.drop_index(op.f('ix_inventory_items_tenant_id'), table_name='inventory_items')
    op.drop_table('inventory_items')
