"""scheme_tiers table + enrollment tier selection/snapshot (merges heads)

Revision ID: b2d4e6f8a0c1
Revises: a1c2d3e4f5a6, a4d6b90c1f37
Create Date: 2026-08-30 10:00:00

NOTE — this revision also MERGES two pre-existing heads. The tree had branched
at c3a8f21b9e47: one branch went c3a8f21b9e47 -> 00ec5a9151da -> a4d6b90c1f37
(users.google_sub), the other went c3a8f21b9e47 -> a1c2d3e4f5a6 (users.
date_of_birth). Both were open heads. This migration descends from BOTH, so the
tree has exactly one head again. The two branches touch disjoint columns
(users.google_sub vs users.date_of_birth) and neither overlaps the scheme tables
altered here, so the merge carries no data conflict.

Scheme Tier Plans. Additive only, fully reversible:
  * NEW TABLE scheme_tiers — one selectable (monthly_amount, duration_months)
    plan per scheme, uniquely constrained per scheme so the same combo can't be
    listed twice. Maturity is derived (amount x months), never stored.
  * scheme_enrollments gains three NULLABLE columns:
      - scheme_tier_id       FK -> scheme_tiers (ON DELETE SET NULL)
      - selected_monthly_amount
      - selected_duration_months
    They snapshot the terms chosen at enrollment so a later tier edit only
    affects NEW enrollments. All nullable: existing rows stay valid and fall
    back to scheme.monthly_amount / scheme.duration_months.

No existing column is altered or dropped and no data is backfilled.
"""
from alembic import op
import sqlalchemy as sa


revision = "b2d4e6f8a0c1"
# Tuple down_revision => this is also a merge of the two open heads.
down_revision = ("a1c2d3e4f5a6", "a4d6b90c1f37")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scheme_tiers",
        sa.Column("id", sa.String(length=50), nullable=False),
        sa.Column("scheme_id", sa.String(length=50), nullable=False),
        sa.Column("monthly_amount", sa.Float(), nullable=False),
        sa.Column("duration_months", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["scheme_id"], ["schemes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scheme_id", "monthly_amount", "duration_months",
            name="uq_scheme_tiers_scheme_amount_duration",
        ),
    )
    op.create_index(op.f("ix_scheme_tiers_scheme_id"), "scheme_tiers", ["scheme_id"], unique=False)
    op.create_index(op.f("ix_scheme_tiers_is_active"), "scheme_tiers", ["is_active"], unique=False)

    op.add_column("scheme_enrollments", sa.Column("scheme_tier_id", sa.String(length=50), nullable=True))
    op.add_column("scheme_enrollments", sa.Column("selected_monthly_amount", sa.Float(), nullable=True))
    op.add_column("scheme_enrollments", sa.Column("selected_duration_months", sa.Integer(), nullable=True))
    op.create_index(
        op.f("ix_scheme_enrollments_scheme_tier_id"), "scheme_enrollments", ["scheme_tier_id"], unique=False
    )
    op.create_foreign_key(
        "fk_scheme_enrollments_scheme_tier_id",
        "scheme_enrollments", "scheme_tiers",
        ["scheme_tier_id"], ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_scheme_enrollments_scheme_tier_id", "scheme_enrollments", type_="foreignkey")
    op.drop_index(op.f("ix_scheme_enrollments_scheme_tier_id"), table_name="scheme_enrollments")
    op.drop_column("scheme_enrollments", "selected_duration_months")
    op.drop_column("scheme_enrollments", "selected_monthly_amount")
    op.drop_column("scheme_enrollments", "scheme_tier_id")
    op.drop_index(op.f("ix_scheme_tiers_is_active"), table_name="scheme_tiers")
    op.drop_index(op.f("ix_scheme_tiers_scheme_id"), table_name="scheme_tiers")
    op.drop_table("scheme_tiers")
