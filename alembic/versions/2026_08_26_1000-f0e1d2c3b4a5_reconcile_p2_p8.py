"""reconcile p2-p8 onto production promotion head

Reconciliation migration. Production applied the promotion migration
c5f3a1b7e28d directly on top of Phase 1 (f5c1d8a3e7b2), so the Phase 2/3/5/7/8
schema was never created there. This ONE additive migration, whose parent is
the production-applied head c5f3a1b7e28d, creates exactly those missing objects
in order — identical upgrade() bodies to the original per-phase migrations,
concatenated verbatim so nothing drifts. It recreates nothing that already
exists on production (which holds only through c5f3a1b7e28d).

The original per-phase migration files (a3f9c1e07b21, b4e2d9f16c33,
d6a1f2b8c490, e7b3c9a1d5f2, f8c4d2a6b193) are preserved on the local `main`
history branch and are NOT part of this deployment lineage, so there is exactly
one forward path and one head from the production revision.

Revision ID: f0e1d2c3b4a5
Revises: c5f3a1b7e28d
Create Date: 2026-08-26 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f0e1d2c3b4a5'
down_revision: Union[str, None] = 'c5f3a1b7e28d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── from 20_1000-a3f9c1e07b21_scheme_requests ──
    op.create_table(
        "scheme_requests",
        sa.Column("id", sa.String(length=50), nullable=False),
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column("customer_id", sa.String(length=50), nullable=False),
        sa.Column("scheme_id", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("kyc_status_at_request", sa.String(length=20), nullable=True),
        sa.Column("enrollment_id", sa.String(length=50), nullable=True),
        sa.Column("rejection_reason", sa.String(length=500), nullable=True),
        sa.Column("requested_by", sa.String(length=50), nullable=False),
        sa.Column("approved_by", sa.String(length=50), nullable=True),
        sa.Column("rejected_by", sa.String(length=50), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scheme_id"], ["schemes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["enrollment_id"], ["scheme_enrollments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["rejected_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("enrollment_id", name="uq_scheme_requests_enrollment"),
    )
    op.create_index(op.f("ix_scheme_requests_tenant_id"), "scheme_requests", ["tenant_id"])
    op.create_index(op.f("ix_scheme_requests_customer_id"), "scheme_requests", ["customer_id"])
    op.create_index(op.f("ix_scheme_requests_scheme_id"), "scheme_requests", ["scheme_id"])
    op.create_index(op.f("ix_scheme_requests_status"), "scheme_requests", ["status"])

    # ── from 21_1000-b4e2d9f16c33_advance_contributions ──
    op.add_column(
        "payments",
        sa.Column("months_covered", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column("payments", sa.Column("period_start", sa.Date(), nullable=True))
    op.add_column("payments", sa.Column("period_end", sa.Date(), nullable=True))

    op.add_column(
        "scheme_enrollments",
        sa.Column("months_paid", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("scheme_enrollments", sa.Column("next_due_date", sa.Date(), nullable=True))

    # â”€â”€ Backfill coverage from the existing successful-payment ledger â”€â”€
    # months_paid = min(count(successful payments), duration_months)
    op.execute(
        """
        UPDATE scheme_enrollments e
        SET months_paid = LEAST(
            COALESCE((
                SELECT COUNT(*) FROM payments p
                WHERE p.enrollment_id = e.id
                  AND p.tenant_id = e.tenant_id
                  AND p.payment_status = 'SUCCESS'
            ), 0),
            COALESCE((
                SELECT s.duration_months FROM schemes s WHERE s.id = e.scheme_id
            ), 0)
        )
        """
    )
    # next_due_date = joined_date + months_paid months, NULL once fully covered.
    op.execute(
        """
        UPDATE scheme_enrollments e
        SET next_due_date = CASE
            WHEN e.months_paid < COALESCE(
                (SELECT s.duration_months FROM schemes s WHERE s.id = e.scheme_id), 0)
            THEN (e.joined_date + (e.months_paid || ' months')::interval)::date
            ELSE NULL
        END
        """
    )

    # ── from 23_1000-d6a1f2b8c490_otp_challenges ──
    op.create_table(
        "otp_challenges",
        sa.Column("id", sa.String(length=50), nullable=False),
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column("customer_id", sa.String(length=50), nullable=False),
        sa.Column("purpose", sa.String(length=30), nullable=False),
        sa.Column("sale_id", sa.String(length=50), nullable=True),
        sa.Column("code_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="5", nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sale_id"], ["sales.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_otp_challenges_tenant_id"), "otp_challenges", ["tenant_id"])
    op.create_index(op.f("ix_otp_challenges_customer_id"), "otp_challenges", ["customer_id"])
    op.create_index(op.f("ix_otp_challenges_sale_id"), "otp_challenges", ["sale_id"])
    op.create_index("ix_otp_active_lookup", "otp_challenges", ["tenant_id", "customer_id", "purpose", "sale_id"])

    # ── from 24_1000-e7b3c9a1d5f2_collection_reminders ──
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

    # ── from 25_1000-f8c4d2a6b193_enrollment_remarks ──
    op.add_column("scheme_enrollments", sa.Column("remarks", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("scheme_enrollments", "remarks")

    op.drop_index(op.f("ix_collection_reminders_customer_id"), table_name="collection_reminders")
    op.drop_index(op.f("ix_collection_reminders_enrollment_id"), table_name="collection_reminders")
    op.drop_index(op.f("ix_collection_reminders_tenant_id"), table_name="collection_reminders")
    op.drop_table("collection_reminders")

    op.drop_index("ix_otp_active_lookup", table_name="otp_challenges")
    op.drop_index(op.f("ix_otp_challenges_sale_id"), table_name="otp_challenges")
    op.drop_index(op.f("ix_otp_challenges_customer_id"), table_name="otp_challenges")
    op.drop_index(op.f("ix_otp_challenges_tenant_id"), table_name="otp_challenges")
    op.drop_table("otp_challenges")

    op.drop_column("scheme_enrollments", "next_due_date")
    op.drop_column("scheme_enrollments", "months_paid")
    op.drop_column("payments", "period_end")
    op.drop_column("payments", "period_start")
    op.drop_column("payments", "months_covered")

    op.drop_index(op.f("ix_scheme_requests_status"), table_name="scheme_requests")
    op.drop_index(op.f("ix_scheme_requests_scheme_id"), table_name="scheme_requests")
    op.drop_index(op.f("ix_scheme_requests_customer_id"), table_name="scheme_requests")
    op.drop_index(op.f("ix_scheme_requests_tenant_id"), table_name="scheme_requests")
    op.drop_table("scheme_requests")
