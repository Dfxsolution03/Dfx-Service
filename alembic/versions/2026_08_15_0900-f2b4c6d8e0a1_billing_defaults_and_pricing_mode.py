"""billing defaults (vendor/category/store) and pricing_mode

Revision ID: f2b4c6d8e0a1
Revises: e1a2b3c4d5f6
Create Date: 2026-08-15 09:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'f2b4c6d8e0a1'
down_revision: Union[str, None] = 'e1a2b3c4d5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('vendors', sa.Column('default_making_charge_type', sa.String(length=20), nullable=True))
    op.add_column('vendors', sa.Column('default_making_charge_value', sa.Float(), nullable=True))
    op.add_column('vendors', sa.Column('default_wastage_type', sa.String(length=20), nullable=True))
    op.add_column('vendors', sa.Column('default_wastage_value', sa.Float(), nullable=True))
    op.add_column('vendors', sa.Column('default_stone_charge_amount', sa.Float(), nullable=True))
    op.add_column('vendors', sa.Column('default_other_charges_amount', sa.Float(), nullable=True))
    op.add_column('vendors', sa.Column('default_tax_rate_percent', sa.Float(), nullable=True))
    op.add_column('vendors', sa.Column('default_pricing_mode', sa.String(length=20), nullable=True))

    op.add_column('inventory_items', sa.Column('pricing_mode', sa.String(length=20), nullable=True))
    op.add_column('sales', sa.Column('pricing_mode', sa.String(length=20), nullable=True))

    op.create_table(
        'category_pricing_defaults',
        sa.Column('id', sa.String(length=50), nullable=False),
        sa.Column('tenant_id', sa.String(length=50), nullable=False),
        sa.Column('category', sa.String(length=100), nullable=False),
        sa.Column('making_charge_type', sa.String(length=20), nullable=True),
        sa.Column('making_charge_value', sa.Float(), nullable=True),
        sa.Column('wastage_type', sa.String(length=20), nullable=True),
        sa.Column('wastage_value', sa.Float(), nullable=True),
        sa.Column('stone_charge_amount', sa.Float(), nullable=True),
        sa.Column('other_charges_amount', sa.Float(), nullable=True),
        sa.Column('tax_rate_percent', sa.Float(), nullable=True),
        sa.Column('default_pricing_mode', sa.String(length=20), nullable=True),
        sa.Column('created_by', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'category', name='uq_category_pricing_defaults_tenant_category'),
    )
    op.create_index(op.f('ix_category_pricing_defaults_tenant_id'), 'category_pricing_defaults', ['tenant_id'], unique=False)

    op.create_table(
        'tenant_billing_defaults',
        sa.Column('id', sa.String(length=50), nullable=False),
        sa.Column('tenant_id', sa.String(length=50), nullable=False),
        sa.Column('making_charge_type', sa.String(length=20), nullable=True),
        sa.Column('making_charge_value', sa.Float(), nullable=True),
        sa.Column('wastage_type', sa.String(length=20), nullable=True),
        sa.Column('wastage_value', sa.Float(), nullable=True),
        sa.Column('stone_charge_amount', sa.Float(), nullable=True),
        sa.Column('other_charges_amount', sa.Float(), nullable=True),
        sa.Column('tax_rate_percent', sa.Float(), nullable=True),
        sa.Column('default_pricing_mode', sa.String(length=20), nullable=True),
        sa.Column('created_by', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', name='uq_tenant_billing_defaults_tenant_id'),
    )


def downgrade() -> None:
    op.drop_table('tenant_billing_defaults')

    op.drop_index(op.f('ix_category_pricing_defaults_tenant_id'), table_name='category_pricing_defaults')
    op.drop_table('category_pricing_defaults')

    op.drop_column('sales', 'pricing_mode')
    op.drop_column('inventory_items', 'pricing_mode')

    op.drop_column('vendors', 'default_pricing_mode')
    op.drop_column('vendors', 'default_tax_rate_percent')
    op.drop_column('vendors', 'default_other_charges_amount')
    op.drop_column('vendors', 'default_stone_charge_amount')
    op.drop_column('vendors', 'default_wastage_value')
    op.drop_column('vendors', 'default_wastage_type')
    op.drop_column('vendors', 'default_making_charge_value')
    op.drop_column('vendors', 'default_making_charge_type')
