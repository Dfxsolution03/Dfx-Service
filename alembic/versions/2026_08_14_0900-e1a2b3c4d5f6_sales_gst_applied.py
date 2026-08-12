"""sales gst_applied flag

Revision ID: e1a2b3c4d5f6
Revises: d8e2f6a1b3c4
Create Date: 2026-08-14 09:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'e1a2b3c4d5f6'
down_revision: Union[str, None] = 'd8e2f6a1b3c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('sales', sa.Column('gst_applied', sa.Boolean(), nullable=False, server_default='true'))
    op.alter_column('sales', 'gst_applied', server_default=None)


def downgrade() -> None:
    op.drop_column('sales', 'gst_applied')
