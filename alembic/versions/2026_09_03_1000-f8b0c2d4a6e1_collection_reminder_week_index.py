"""collection_reminders.week_index (Phase 9 — weekly overdue recurrence)

Revision ID: f8b0c2d4a6e1
Revises: e6a8b2d4f0c1
Create Date: 2026-09-03 10:00:00

Phase 9 — weekly overdue reminders. Smallest additive change to let a still-
unpaid installment be re-reminded every 7 days:
  * ADD collection_reminders.week_index (int, NOT NULL, server_default 0) —
    existing rows backfill to 0 automatically via the server default.
  * REPLACE the dedup unique key: drop uq_collection_reminder_period
    (enrollment_id, due_date) and add uq_collection_reminder_period_week
    (enrollment_id, due_date, week_index), so a new 7-day bucket is allowed
    while duplicates within the same bucket are still blocked.

No data is deleted or rewritten; historical reminders remain valid (week_index
0). Downgrade note: reverting to the (enrollment_id, due_date) unique key
assumes no enrollment/due_date has more than one weekly reminder row; if weekly
reminders were already produced, remove the extras before downgrading.
"""
from alembic import op
import sqlalchemy as sa


revision = "f8b0c2d4a6e1"
down_revision = "e6a8b2d4f0c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "collection_reminders",
        sa.Column("week_index", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.drop_constraint("uq_collection_reminder_period", "collection_reminders", type_="unique")
    op.create_unique_constraint(
        "uq_collection_reminder_period_week",
        "collection_reminders",
        ["enrollment_id", "due_date", "week_index"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_collection_reminder_period_week", "collection_reminders", type_="unique")
    op.create_unique_constraint(
        "uq_collection_reminder_period",
        "collection_reminders",
        ["enrollment_id", "due_date"],
    )
    op.drop_column("collection_reminders", "week_index")
