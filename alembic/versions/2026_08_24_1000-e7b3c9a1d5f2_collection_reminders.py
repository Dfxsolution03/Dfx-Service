"""collection reminders (overdue scheme reminders)

Phase 7 — adds collection_reminders. Purely additive: one new table, no existing
table touched. UNIQUE(enrollment_id, due_date) enforces one reminder per period.

Revision ID: e7b3c9a1d5f2
Revises: d6a1f2b8c490
Create Date: 2026-08-24 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e7b3c9a1d5f2'
down_revision: Union[str, None] = 'd6a1f2b8c490'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "collection_reminders",
        sa.Column("id", sa.String(length=50), nullable=False),
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column("enrollment_id", sa.String(length=50), nullable=False),
        sa.Column("customer_id", sa.String(length=50), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("overdue_days", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["enrollment_id"], ["scheme_enrollments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("enrollment_id", "due_date", name="uq_collection_reminder_period"),
    )
    op.create_index(op.f("ix_collection_reminders_tenant_id"), "collection_reminders", ["tenant_id"])
    op.create_index(op.f("ix_collection_reminders_enrollment_id"), "collection_reminders", ["enrollment_id"])
    op.create_index(op.f("ix_collection_reminders_customer_id"), "collection_reminders", ["customer_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_collection_reminders_customer_id"), table_name="collection_reminders")
    op.drop_index(op.f("ix_collection_reminders_enrollment_id"), table_name="collection_reminders")
    op.drop_index(op.f("ix_collection_reminders_tenant_id"), table_name="collection_reminders")
    op.drop_table("collection_reminders")
