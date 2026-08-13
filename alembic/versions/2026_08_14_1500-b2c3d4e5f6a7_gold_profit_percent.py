"""add gold_profit_percent (store margin on gold value only)

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6

Additive only. Stone/other charges remain on vendors/category_pricing_defaults/
tenant_billing_defaults (unused going forward, not dropped -- no data loss).
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None

_DEFAULT_TABLES = ['vendors', 'category_pricing_defaults', 'tenant_billing_defaults']


def upgrade() -> None:
    for table in _DEFAULT_TABLES:
        op.add_column(table, sa.Column('gold_profit_percent', sa.Float(), nullable=True))
    op.add_column('inventory_items', sa.Column('gold_profit_percent', sa.Float(), nullable=False, server_default='0'))
    op.add_column('sales', sa.Column('gold_profit_percent', sa.Float(), nullable=False, server_default='0'))
    op.add_column('sales', sa.Column('gold_profit_amount', sa.Float(), nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('sales', 'gold_profit_amount')
    op.drop_column('sales', 'gold_profit_percent')
    op.drop_column('inventory_items', 'gold_profit_percent')
    for table in _DEFAULT_TABLES:
        op.drop_column(table, 'gold_profit_percent')
