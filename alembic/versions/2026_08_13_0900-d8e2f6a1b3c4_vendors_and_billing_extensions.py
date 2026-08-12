"""vendors and billing extensions

Revision ID: d8e2f6a1b3c4
Revises: c3f7a1e9d4b2
Create Date: 2026-08-13 09:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'd8e2f6a1b3c4'
down_revision: Union[str, None] = 'c3f7a1e9d4b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'vendors',
        sa.Column('id', sa.String(length=50), nullable=False),
        sa.Column('tenant_id', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('contact_person', sa.String(length=150), nullable=True),
        sa.Column('phone', sa.String(length=20), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('address', sa.String(length=500), nullable=True),
        sa.Column('gst_number', sa.String(length=20), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_by', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_vendors_tenant_id'), 'vendors', ['tenant_id'], unique=False)

    op.add_column('inventory_items', sa.Column('vendor_id', sa.String(length=50), nullable=True))
    op.add_column('inventory_items', sa.Column('purchase_rate_per_gram', sa.Float(), nullable=True))
    op.create_index(op.f('ix_inventory_items_vendor_id'), 'inventory_items', ['vendor_id'], unique=False)
    op.create_foreign_key(
        'fk_inventory_items_vendor_id', 'inventory_items', 'vendors', ['vendor_id'], ['id'], ondelete='SET NULL'
    )

    op.add_column('sales', sa.Column('vendor_name', sa.String(length=200), nullable=True))
    op.add_column('sales', sa.Column('payment_method', sa.String(length=30), nullable=False, server_default='CASH'))
    op.add_column('sales', sa.Column('payment_status', sa.String(length=20), nullable=False, server_default='PAID'))
    op.alter_column('sales', 'payment_method', server_default=None)
    op.alter_column('sales', 'payment_status', server_default=None)


def downgrade() -> None:
    op.drop_column('sales', 'payment_status')
    op.drop_column('sales', 'payment_method')
    op.drop_column('sales', 'vendor_name')

    op.drop_constraint('fk_inventory_items_vendor_id', 'inventory_items', type_='foreignkey')
    op.drop_index(op.f('ix_inventory_items_vendor_id'), table_name='inventory_items')
    op.drop_column('inventory_items', 'purchase_rate_per_gram')
    op.drop_column('inventory_items', 'vendor_id')

    op.drop_index(op.f('ix_vendors_tenant_id'), table_name='vendors')
    op.drop_table('vendors')
