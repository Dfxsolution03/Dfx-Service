"""advance contributions coverage + next_due_date

Phase 3 — advance scheme contributions (1/3/6 months in one transaction) and
per-enrollment coverage tracking.

Production safety notes:

* Purely additive: five new columns across two existing tables. No column is
  dropped or retyped, no financial value is rewritten, no ledger row changes.
* payments.months_covered defaults to 1 (server_default '1') so every existing
  contribution reads as a single monthly installment — its meaning before
  Phase 3. period_start/period_end are nullable and left NULL for history.
* scheme_enrollments.months_paid defaults to 0; next_due_date nullable.
* Backfill is idempotent and deterministic:
    - months_paid := number of SUCCESSFUL payments for the enrollment, capped at
      the scheme duration (historical payments were one installment each).
    - next_due_date := joined_date + months_paid months, or NULL once fully
      covered. Re-running recomputes the same values from the same source rows.
  Balance in rupees is unaffected — it stays derived from the payment ledger.

Revision ID: b4e2d9f16c33
Revises: a3f9c1e07b21
Create Date: 2026-08-21 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b4e2d9f16c33'
down_revision: Union[str, None] = 'a3f9c1e07b21'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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

    # ── Backfill coverage from the existing successful-payment ledger ──
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


def downgrade() -> None:
    op.drop_column("scheme_enrollments", "next_due_date")
    op.drop_column("scheme_enrollments", "months_paid")
    op.drop_column("payments", "period_end")
    op.drop_column("payments", "period_start")
    op.drop_column("payments", "months_covered")
