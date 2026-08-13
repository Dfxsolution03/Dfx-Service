"""fix vendor default column names to match schema/service field names

Revision ID: a1b2c3d4e5f6
Revises: f2b4c6d8e0a1
Create Date: 2026-08-15 12:00:00.000000

The Vendor model's default_making_charge_type/value, default_wastage_type/
value, default_stone_charge_amount, default_other_charges_amount, and
default_tax_rate_percent columns were named with a "default_" prefix that
never matched BillingDefaultFields/_DEFAULT_FIELD_NAMES (which use the
unprefixed names, matching CategoryPricingDefault/TenantBillingDefaults).
setattr() on the ORM object was silently creating throwaway, non-mapped
Python attributes instead of touching these real columns, so Vendor
defaults for these five fields never actually persisted. All values are
still null (confirmed on production before writing this migration), so
this is a pure rename — no data loss.
"""
from typing import Sequence, Union
from alembic import op


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'f2b4c6d8e0a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RENAMES = [
    ('default_making_charge_type', 'making_charge_type'),
    ('default_making_charge_value', 'making_charge_value'),
    ('default_wastage_type', 'wastage_type'),
    ('default_wastage_value', 'wastage_value'),
    ('default_stone_charge_amount', 'stone_charge_amount'),
    ('default_other_charges_amount', 'other_charges_amount'),
    ('default_tax_rate_percent', 'tax_rate_percent'),
]


def upgrade() -> None:
    for old_name, new_name in _RENAMES:
        op.alter_column('vendors', old_name, new_column_name=new_name)


def downgrade() -> None:
    for old_name, new_name in _RENAMES:
        op.alter_column('vendors', new_name, new_column_name=old_name)
