"""customer code and tenant sequence

Phase 1 — adds the human-readable, tenant-scoped, immutable customer code
(DFX-CUST-000001) and the per-tenant counter that hands it out.

Production safety notes:

* Purely additive. No column is dropped or retyped, no existing value is
  rewritten, and no financial table is touched. users.id is untouched — every
  existing relationship keeps pointing at the same key.
* users.customer_code is added NULLABLE and stays nullable. It cannot be NOT
  NULL because the users table also holds Admin, Staff and SuperAdmin rows,
  which have no customer code by definition. The invariant that matters —
  "no two customers in a tenant share a code" — is enforced by the unique
  constraint below, not by NOT NULL. NULLs are distinct under that constraint
  in both PostgreSQL and SQLite, so uncoded rows never collide.
* The backfill only ever writes rows WHERE customer_code IS NULL, so running
  it again assigns nothing and cannot produce a second code for a customer.
* Numbering is deterministic: per tenant, ordered by created_at then id, so a
  re-run on the same data would reproduce the same assignment.

Revision ID: f5c1d8a3e7b2
Revises: e4a7c2b9d6f1
Create Date: 2026-08-19 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f5c1d8a3e7b2'
down_revision: Union[str, None] = 'e4a7c2b9d6f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CUSTOMER_CODE_PREFIX = "DFX-CUST-"


def upgrade() -> None:
    # 1. Additive nullable column.
    op.add_column("users", sa.Column("customer_code", sa.String(length=32), nullable=True))
    op.create_index("ix_users_customer_code", "users", ["customer_code"])

    # 2. Per-tenant counter table backing the sequence.
    op.create_table(
        "customer_code_sequences",
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column("last_value", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )

    # 3. Backfill existing customers, then seed each tenant's counter past the
    #    highest number handed out, so newly registered customers continue the
    #    same series instead of colliding with a backfilled one.
    conn = op.get_bind()

    customers = conn.execute(
        sa.text(
            """
            SELECT u.id, u.tenant_id
            FROM users u
            JOIN roles r ON r.id = u.role_id
            WHERE r.name = 'Customer'
              AND u.tenant_id IS NOT NULL
              AND u.customer_code IS NULL
            ORDER BY u.tenant_id, u.created_at, u.id
            """
        )
    ).fetchall()

    # Start each tenant at whatever it has already issued (normally nothing on
    # first run; non-zero if a partial backfill ever ran before).
    counters: dict = {}
    for tenant_id, in conn.execute(
        sa.text("SELECT DISTINCT tenant_id FROM users WHERE tenant_id IS NOT NULL")
    ).fetchall():
        existing = conn.execute(
            sa.text(
                "SELECT COUNT(*) FROM users "
                "WHERE tenant_id = :t AND customer_code IS NOT NULL"
            ),
            {"t": tenant_id},
        ).scalar_one()
        counters[tenant_id] = int(existing or 0)

    for user_id, tenant_id in customers:
        counters[tenant_id] = counters.get(tenant_id, 0) + 1
        code = f"{CUSTOMER_CODE_PREFIX}{counters[tenant_id]:06d}"
        conn.execute(
            sa.text(
                "UPDATE users SET customer_code = :code "
                "WHERE id = :uid AND customer_code IS NULL"
            ),
            {"code": code, "uid": user_id},
        )

    for tenant_id, last_value in counters.items():
        conn.execute(
            sa.text(
                "INSERT INTO customer_code_sequences (tenant_id, last_value) "
                "VALUES (:t, :v)"
            ),
            {"t": tenant_id, "v": last_value},
        )

    # 4. Enforce the invariant only after the data is clean.
    op.create_unique_constraint(
        "uq_users_tenant_customer_code", "users", ["tenant_id", "customer_code"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_users_tenant_customer_code", "users", type_="unique")
    op.drop_table("customer_code_sequences")
    op.drop_index("ix_users_customer_code", table_name="users")
    op.drop_column("users", "customer_code")
