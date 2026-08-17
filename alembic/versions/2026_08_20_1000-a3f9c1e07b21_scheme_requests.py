"""scheme request lifecycle

Phase 2 — adds the scheme_requests table, the gate a customer's scheme-join
request passes through (REQUESTED -> APPROVED / REJECTED) before an enrollment
is ever created.

Production safety notes:

* Purely additive. Creates ONE new table. No existing column is dropped,
  retyped or rewritten, and no financial table (payments, sales, redemptions,
  enrollments) is touched. Existing relationships keep pointing at the same keys.
* enrollment_id is UNIQUE (uq_scheme_requests_enrollment) so a single request
  can never be tied to two enrollments — defence in depth behind the row-locked,
  status-guarded approval transaction.
* enrollment_id uses ON DELETE SET NULL: deleting an enrollment (should never
  happen — enrollments are immutable financial records) would not cascade-delete
  the historical request row.
* approved_by / rejected_by use ON DELETE SET NULL so removing an admin user
  never destroys request history; customer_id / requested_by / tenant_id /
  scheme_id cascade with their owning rows, matching existing conventions.

Revision ID: a3f9c1e07b21
Revises: f5c1d8a3e7b2
Create Date: 2026-08-20 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a3f9c1e07b21'
down_revision: Union[str, None] = 'f5c1d8a3e7b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.drop_index(op.f("ix_scheme_requests_status"), table_name="scheme_requests")
    op.drop_index(op.f("ix_scheme_requests_scheme_id"), table_name="scheme_requests")
    op.drop_index(op.f("ix_scheme_requests_customer_id"), table_name="scheme_requests")
    op.drop_index(op.f("ix_scheme_requests_tenant_id"), table_name="scheme_requests")
    op.drop_table("scheme_requests")
