from datetime import datetime
from typing import Optional, List
from sqlalchemy import String, Boolean, DateTime, ForeignKey, Text, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="Active", nullable=False)
    # Module 29 — additive, nullable business-contact/branding columns needed
    # for real tenant provisioning (previously Tenant had none of these — see
    # SESSION_HANDOFF.md §8/§14). All nullable so every pre-existing tenant
    # row stays valid unchanged; existing queries/behavior untouched.
    contact_email: Mapped[Optional[str]] = mapped_column(String(255), unique=True, index=True, nullable=True)
    contact_phone: Mapped[Optional[str]] = mapped_column(String(20), unique=True, index=True, nullable=True)
    gst_number: Mapped[Optional[str]] = mapped_column(String(20), unique=True, index=True, nullable=True)
    brand_color: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    logo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Relationships
    subscriptions: Mapped[List["Subscription"]] = relationship(
        "Subscription", back_populates="tenant", cascade="all, delete-orphan"
    )
    users: Mapped[List["User"]] = relationship(
        "User", back_populates="tenant", cascade="all, delete-orphan"
    )


class Subscription(Base, TimestampMixin):
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan: Mapped[str] = mapped_column(String(50), default="Professional", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="Active", nullable=False)
    trial_ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    current_period_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="subscriptions")


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Relationships
    permissions: Mapped[List["Permission"]] = relationship(
        "Permission", secondary="role_permissions", back_populates="roles"
    )
    users: Mapped[List["User"]] = relationship("User", back_populates="role")


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    code: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Relationships
    roles: Mapped[List["Role"]] = relationship(
        "Role", secondary="role_permissions", back_populates="permissions"
    )


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (
        # Tenant-scoped uniqueness for the human-readable customer code. NULLs
        # are distinct in both PostgreSQL and SQLite, so Admin/Staff/SuperAdmin
        # rows (which never carry a code) do not collide with each other.
        UniqueConstraint("tenant_id", "customer_code", name="uq_users_tenant_customer_code"),
    )

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    tenant_id: Mapped[Optional[str]] = mapped_column(
        String(50), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    role_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("roles.id"), nullable=False, index=True
    )
    email: Mapped[Optional[str]] = mapped_column(String(255), index=True, nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(20), index=True, nullable=True)
    # Google's `sub` claim — the stable, never-reused identifier for a linked
    # Google account (see app/services/google_identity_service.py). Additive
    # and nullable: every user who has never signed in with Google keeps NULL,
    # and NULLs are distinct under a unique index in both PostgreSQL and
    # SQLite, so any number of them coexist. Same "value not just flag"
    # convention as email_verified_at below. Never accepted from a client —
    # only ever written from a verified ID token.
    google_sub: Mapped[Optional[str]] = mapped_column(
        String(255), unique=True, index=True, nullable=True
    )
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    kyc_status: Mapped[str] = mapped_column(String(20), default="Pending", nullable=False)
    # Human-readable, tenant-scoped, immutable customer identifier —
    # "DFX-CUST-000001". Assigned by the backend at customer creation and never
    # accepted from a client; the numeric part is zero-padded to six digits but
    # is not capped there (a tenant past 999999 customers simply produces a
    # longer code). NULL for every non-Customer user, which is why the column
    # stays nullable — the users table holds Admin/Staff/SuperAdmin rows too.
    # User.id remains the internal key for every relationship; this code is an
    # additional, display/search-facing identity only.
    customer_code: Mapped[Optional[str]] = mapped_column(String(32), index=True, nullable=True)
    member_since: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    date_of_birth: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Staff-only module access grants — comma-separated STAFF_MODULE keys
    # (see app/core/constants.py). Same "plain Text, manual (de)serialization
    # at the service boundary" convention as CatalogueDesign.canvas_json,
    # rather than a first-of-its-kind JSON column. NULL/empty for every
    # non-Staff role — Admin/SuperAdmin access is never gated by this.
    staff_permissions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Module 18 — nullable timestamp, same "value not just flag" convention as
    # KYCRecord.verified_at. NULL = not verified. Set once, never cleared.
    email_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    tenant: Mapped[Optional["Tenant"]] = relationship("Tenant", back_populates="users")
    role: Mapped["Role"] = relationship("Role", back_populates="users")
    refresh_tokens: Mapped[List["RefreshToken"]] = relationship(
        "RefreshToken", back_populates="user", cascade="all, delete-orphan"
    )
    password_reset_tokens: Mapped[List["PasswordResetToken"]] = relationship(
        "PasswordResetToken", back_populates="user", cascade="all, delete-orphan"
    )
    email_verification_tokens: Mapped[List["EmailVerificationToken"]] = relationship(
        "EmailVerificationToken", back_populates="user", cascade="all, delete-orphan"
    )


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    device_info: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="refresh_tokens")


class PasswordResetToken(Base):
    """
    Module 18 — mirrors RefreshToken's exact security pattern: the raw token
    is emailed to the user and never persisted; only its SHA256 hash is
    stored here (see app/services/token_service.py). `used_at` (nullable,
    set-once) enforces one-time use — same convention as KYCRecord.verified_at
    rather than a plain boolean, so the audit trail shows *when* it was used.
    """
    __tablename__ = "password_reset_tokens"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="password_reset_tokens")


class EmailVerificationToken(Base):
    """
    Module 18 — same pattern as PasswordResetToken (hashed-at-rest, one-time
    use via `used_at`), kept as its own table rather than a shared/polymorphic
    "purpose" column — this codebase's established convention is one table
    per concern (see RefreshToken vs. PasswordResetToken vs. this one), not
    polymorphic multi-purpose tables. The actual token generation/hashing
    logic is still centralized in app/services/token_service.py so that
    security-sensitive code isn't duplicated between the two features.
    """
    __tablename__ = "email_verification_tokens"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="email_verification_tokens")
