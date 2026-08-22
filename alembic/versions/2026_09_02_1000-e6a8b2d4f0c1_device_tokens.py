"""device_tokens table (Phase 7 — push device registration)

Revision ID: e6a8b2d4f0c1
Revises: d5f7a1c3e9b4
Create Date: 2026-09-02 10:00:00

Phase 7 — Notifications. Additive only, fully reversible: one NEW table
`device_tokens` holding customer push registrations (FCM/APNs/Expo), unique per
(tenant_id, token). No existing table/column is altered or dropped and no data
is backfilled. A row here is only a delivery address — push delivery is real
only when a provider is configured (push_service), never faked.
"""
from alembic import op
import sqlalchemy as sa


revision = "e6a8b2d4f0c1"
down_revision = "d5f7a1c3e9b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "device_tokens",
        sa.Column("id", sa.String(length=50), nullable=False),
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("token", sa.String(length=512), nullable=False),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("provider", sa.String(length=20), server_default="FCM", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "token", name="uq_device_tokens_tenant_token"),
    )
    op.create_index(op.f("ix_device_tokens_tenant_id"), "device_tokens", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_device_tokens_user_id"), "device_tokens", ["user_id"], unique=False)
    op.create_index(op.f("ix_device_tokens_is_active"), "device_tokens", ["is_active"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_device_tokens_is_active"), table_name="device_tokens")
    op.drop_index(op.f("ix_device_tokens_user_id"), table_name="device_tokens")
    op.drop_index(op.f("ix_device_tokens_tenant_id"), table_name="device_tokens")
    op.drop_table("device_tokens")
