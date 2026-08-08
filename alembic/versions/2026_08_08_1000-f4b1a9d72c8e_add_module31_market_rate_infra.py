"""add module 31 market rate infrastructure (phase 0)

Revision ID: f4b1a9d72c8e
Revises: e2a7c9b41f36
Create Date: 2026-08-08 10:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f4b1a9d72c8e'
down_revision: Union[str, None] = 'e2a7c9b41f36'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### Module 31 / Phase 0 — Market Rate Infrastructure (additive only) ###
    # The existing gold_rates table is untouched — see downgrade() note.

    # -- market_rates (platform-wide, append-only historical feed) ----------
    op.create_table(
        'market_rates',
        sa.Column('id', sa.String(length=50), nullable=False),
        sa.Column('provider', sa.String(length=30), nullable=False),
        sa.Column('gold_24k', sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column('silver_999', sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column('currency', sa.String(length=3), server_default='INR', nullable=False),
        sa.Column('unit', sa.String(length=20), server_default='PER_GRAM', nullable=False),
        sa.Column('raw_payload', sa.Text(), nullable=True),
        sa.Column('provider_metadata', sa.Text(), nullable=True),
        sa.Column('is_override', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('overridden_by_user_id', sa.String(length=50), nullable=True),
        sa.Column('override_reason', sa.String(length=255), nullable=True),
        sa.Column('fetch_duration_ms', sa.Integer(), nullable=True),
        sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['overridden_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_market_rates_provider'), 'market_rates', ['provider'], unique=False)
    op.create_index(op.f('ix_market_rates_fetched_at'), 'market_rates', ['fetched_at'], unique=False)

    # -- tenant_pricing_config (one row per tenant) --------------------------
    op.create_table(
        'tenant_pricing_config',
        sa.Column('id', sa.String(length=50), nullable=False),
        sa.Column('tenant_id', sa.String(length=50), nullable=False),
        sa.Column('mode', sa.String(length=20), server_default='LIVE_MARKET', nullable=False),
        sa.Column('markup_type', sa.String(length=10), nullable=True),
        sa.Column('markup_gold_value', sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column('markup_silver_value', sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column('manual_gold_24k', sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column('manual_silver_999', sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column('updated_by_user_id', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['updated_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', name='uq_tenant_pricing_config_tenant'),
    )

    # -- provider_health (one row per provider, upserted in place) ----------
    op.create_table(
        'provider_health',
        sa.Column('id', sa.String(length=50), nullable=False),
        sa.Column('provider', sa.String(length=30), nullable=False),
        sa.Column('last_attempt_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_success_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_failure_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('consecutive_failures', sa.Integer(), server_default='0', nullable=False),
        sa.Column('last_error_message', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='UNKNOWN', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('provider', name='uq_provider_health_provider'),
    )
    # ### end Module 31 / Phase 0 table creation ###


def downgrade() -> None:
    # ### Module 31 / Phase 0 — reverse order of upgrade() ###
    # gold_rates is never touched by this migration in either direction.
    op.drop_table('provider_health')

    op.drop_table('tenant_pricing_config')

    op.drop_index(op.f('ix_market_rates_fetched_at'), table_name='market_rates')
    op.drop_index(op.f('ix_market_rates_provider'), table_name='market_rates')
    op.drop_table('market_rates')
    # ### end Module 31 / Phase 0 table drop ###
