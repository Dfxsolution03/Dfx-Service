"""enrollment selected_bonus_percentage snapshot (merges heads)

Revision ID: d9f1b3c5e7a2
Revises: c7e1a2b3d4f5, f8b0c2d4a6e1
Create Date: 2026-09-04 10:00:00

NOTE — this revision also MERGES the two open heads that both descend from
b2d4e6f8a0c1: the scheme-tier-bonus branch (c7e1a2b3d4f5) and the
collection-reminder week_index branch (f8b0c2d4a6e1). The two branches touch
disjoint tables (scheme_tiers vs collection_reminders) and neither overlaps the
scheme_enrollments column added here, so the merge carries no data conflict and
the tree has exactly one head again.

Additive only, fully reversible: scheme_enrollments gains one NULLABLE column
selected_bonus_percentage (Float). It snapshots the selected tier's bonus at
enrollment time so a later tier bonus edit never rewrites an existing
enrollment's maturity. NULL for every existing row (and for base-terms
enrollments) — resolve_enrollment_bonus() treats NULL as 0%, so existing
enrollments keep their current bonus-free maturity. No column is altered or
dropped and no data is backfilled.
"""
from alembic import op
import sqlalchemy as sa


revision = "d9f1b3c5e7a2"
# Tuple down_revision => merges the two open heads into one.
down_revision = ("c7e1a2b3d4f5", "f8b0c2d4a6e1")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scheme_enrollments",
        sa.Column("selected_bonus_percentage", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("scheme_enrollments", "selected_bonus_percentage")
