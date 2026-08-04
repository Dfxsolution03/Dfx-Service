import uuid
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import ROLE_ADMIN
from app.core.logging import logger
from app.core.security import hash_password
from app.models.auth import Tenant, Subscription, Role, User, PasswordResetToken
from app.models.customer import Branch
from app.models.enrollment import STATUS_ACTIVE, STATUS_COMPLETED, STATUS_CANCELLED
from app.repositories.superadmin_repository import SuperAdminRepository
from app.repositories.report_repository import ReportRepository
from app.repositories.audit_repository import AuditRepository
from app.exceptions.base import ResourceNotFoundException, ValidationException, ConflictException
# Reused directly from the Reports module (Module 12) rather than reimplemented —
# same IST-based period resolution and bucket-labeling used everywhere else.
from app.services.report_service import _resolve_range, _label_bucket, _today_ist
from app.services.token_service import TokenService
from app.services.email_service import get_email_provider
from app.schemas.report import DateRangeInfo
from app.schemas.superadmin import (
    TenantListItem,
    TenantDetailResponse,
    TenantStatisticsResponse,
    PlatformGrowthPoint,
    TenantStatusBreakdownItem,
    RecentTenantItem,
    PlatformDashboardResponse,
    TenantProvisionRequest,
    TenantProvisionResponse,
    BranchSummary,
    SubscriptionSummary,
    ProvisionedAdminSummary,
)
from app.schemas.export import ExportFileResponse, ExportFormat
from app.services.export_service import ExportService, ExportColumn

VALID_TENANT_STATUSES = {"Active", "Inactive"}
# Module 29 — sensible fallback when a wizard submission omits Branding's
# optional color picker. Matches this codebase's own platform accent color
# (see src/app/globals.css's --gold, which is actually blue — a rebrand
# leftover name, not this backend's concern) rather than an arbitrary value.
DEFAULT_BRAND_COLOR = "#2C6FBD"


def _admin_contact_fields(admin: Optional[User]) -> dict:
    return {
        "admin_name": admin.name if admin else None,
        "admin_email": admin.email if admin else None,
        "admin_phone": admin.phone if admin else None,
    }


class SuperAdminService:
    """SuperAdmin-only (gated at the endpoint via require_superadmin) — every
    method here operates platform-wide or against an explicit target
    tenant_id, never current_user.tenant_id (SuperAdmin has none)."""

    # ─── Tenants ───

    @staticmethod
    async def get_tenants(
        db: AsyncSession, current_user: User, status_filter: Optional[str]
    ) -> List[TenantListItem]:
        tenants = await SuperAdminRepository.get_tenants(db, status_filter)
        admins_by_tenant = await SuperAdminRepository.get_primary_admins_for_tenants(db, [t.id for t in tenants])
        return [
            TenantListItem(
                id=t.id,
                name=t.name,
                slug=t.slug,
                status=t.status,
                created_at=t.created_at,
                **_admin_contact_fields(admins_by_tenant.get(t.id)),
            )
            for t in tenants
        ]

    @staticmethod
    async def get_tenant_detail(db: AsyncSession, current_user: User, tenant_id: str) -> TenantDetailResponse:
        tenant = await SuperAdminRepository.get_tenant_by_id(db, tenant_id)
        if not tenant:
            raise ResourceNotFoundException(f"Tenant ID '{tenant_id}' not found")
        admin = await SuperAdminRepository.get_primary_admin_for_tenant(db, tenant_id)
        return TenantDetailResponse(
            id=tenant.id,
            name=tenant.name,
            slug=tenant.slug,
            status=tenant.status,
            brand_color=tenant.brand_color,
            logo_url=tenant.logo_url,
            created_at=tenant.created_at,
            updated_at=tenant.updated_at,
            **_admin_contact_fields(admin),
        )

    @staticmethod
    async def set_tenant_status(
        db: AsyncSession, current_user: User, tenant_id: str, new_status: str
    ) -> TenantDetailResponse:
        """Enable/Disable a tenant — a pure status-flag toggle on the Tenant
        row (matches the Scheme.is_active soft-flag convention). Idempotent:
        setting a tenant to its current status is not an error. Does NOT
        cascade to blocking existing user sessions/logins for that tenant —
        that would be a login-flow change, out of scope for this module."""
        if new_status not in VALID_TENANT_STATUSES:
            raise ValidationException(f"Status must be one of: {', '.join(sorted(VALID_TENANT_STATUSES))}")

        tenant = await SuperAdminRepository.get_tenant_by_id(db, tenant_id)
        if not tenant:
            raise ResourceNotFoundException(f"Tenant ID '{tenant_id}' not found")

        before_state = {"status": tenant.status}
        tenant.status = new_status
        after_state = {"status": tenant.status}

        await AuditRepository.create_log(
            db,
            tenant_id=tenant.id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="TENANT_ENABLE" if new_status == "Active" else "TENANT_DISABLE",
            target_entity="tenants",
            target_id=tenant.id,
            before_state=before_state,
            after_state=after_state,
        )

        await db.commit()
        await db.refresh(tenant)

        admin = await SuperAdminRepository.get_primary_admin_for_tenant(db, tenant_id)
        return TenantDetailResponse(
            id=tenant.id,
            name=tenant.name,
            slug=tenant.slug,
            status=tenant.status,
            brand_color=tenant.brand_color,
            logo_url=tenant.logo_url,
            created_at=tenant.created_at,
            updated_at=tenant.updated_at,
            **_admin_contact_fields(admin),
        )

    @staticmethod
    async def provision_tenant(
        db: AsyncSession, current_user: User, req: TenantProvisionRequest
    ) -> TenantProvisionResponse:
        """
        Real tenant provisioning — replaces the old fake "Provision New
        Business" dialog (see SESSION_HANDOFF.md §14/§17/§19). Creates
        Tenant + default Branch + Subscription + Admin User in one
        transaction, generates a temporary password + activation link for
        the new Admin, sends an onboarding email, and audit-logs every
        write. Reuses existing services throughout — no parallel auth,
        RBAC, or multi-tenancy mechanism is introduced:
          - password hashing: app.core.security.hash_password (same as
            every other User in this codebase)
          - activation link: a real PasswordResetToken row (same table,
            model, and hashing TokenService/AuthService.reset_password
            already use) — the link IS a real reset-password link, so
            "first login" is just the existing reset-password page setting
            a real password. No new token table, no new frontend page.
          - audit logging: AuditRepository.create_log, the same append-only
            writer every other module calls.
          - email: get_email_provider() (Module 18) — ConsoleEmailProvider
            in dev, real SMTP once configured, zero new email code.

        Transaction/rollback shape: every uniqueness check below runs
        BEFORE any `db.add()` call, against the session's own
        `autoflush=False` factory (see app/core/database.py) — so a
        validation failure raises before a single row is staged, and
        nothing is ever partially created. Every `db.add()`'d row (tenant,
        subscription, branch, admin user, activation token, 4 audit log
        rows) is flushed together at the one `await db.commit()` call at
        the end — if that commit itself fails (e.g. a race-condition
        uniqueness collision at the DB level), `get_async_db`'s exception
        handler rolls back the whole session, so no partial tenant is ever
        left behind. The onboarding email is sent AFTER the commit,
        deliberately outside the transaction — an email delivery failure
        must never undo an already-successfully-provisioned tenant, the
        same resilience pattern AuthService.forgot_password/
        request_email_verification/register_customer's signup hook already
        established for this exact class of "best-effort side effect".
        """
        # ── Validation (all reads, zero writes — see docstring) ──
        subdomain = req.subdomain.strip().lower()
        if await SuperAdminRepository.get_tenant_by_slug(db, subdomain):
            raise ConflictException(f"Subdomain '{subdomain}' is already taken")

        if req.contact_email and await SuperAdminRepository.get_tenant_by_contact_email(db, req.contact_email):
            raise ConflictException("A tenant with this contact email already exists")

        if await SuperAdminRepository.get_tenant_by_contact_phone(db, req.business_phone):
            raise ConflictException("A tenant with this contact phone already exists")

        if req.gst_number and await SuperAdminRepository.get_tenant_by_gst_number(db, req.gst_number):
            raise ConflictException("A tenant with this GST number already exists")

        existing_admin_email = (
            await db.execute(select(User).where(User.email == req.admin_email))
        ).scalar_one_or_none()
        if existing_admin_email:
            raise ConflictException("An account with this admin email address already exists")

        if req.admin_phone:
            existing_admin_phone = (
                await db.execute(select(User).where(User.phone == req.admin_phone))
            ).scalar_one_or_none()
            if existing_admin_phone:
                raise ConflictException("An account with this admin phone number already exists")

        admin_role = (await db.execute(select(Role).where(Role.name == ROLE_ADMIN))).scalar_one_or_none()
        if not admin_role:
            raise ResourceNotFoundException("Admin role configuration missing in database")

        # ── Create (all writes staged via db.add(), nothing flushed yet) ──
        now = datetime.now(timezone.utc)
        tenant_id = f"tnt_{uuid.uuid4().hex[:12]}"
        tenant = Tenant(
            id=tenant_id,
            name=req.business_name,
            slug=subdomain,
            status="Active",
            contact_email=req.contact_email,
            contact_phone=req.business_phone,
            gst_number=req.gst_number,
            brand_color=req.brand_color or DEFAULT_BRAND_COLOR,
            logo_url=None,
        )
        db.add(tenant)

        subscription_id = f"sub_{uuid.uuid4().hex[:12]}"
        subscription = Subscription(
            id=subscription_id,
            tenant_id=tenant_id,
            plan=req.plan,
            status="Active",
            trial_ends_at=now + timedelta(days=req.trial_days) if req.trial_days > 0 else None,
            current_period_end=None,
        )
        db.add(subscription)

        branch_id = f"brn_{uuid.uuid4().hex[:12]}"
        branch = Branch(
            id=branch_id,
            tenant_id=tenant_id,
            name=f"{req.business_name} — Main Branch",
            address=req.business_address,
            phone=req.business_phone,
            # No geocoding integration exists in this codebase — a real
            # coordinate has to be entered later by the tenant. Disclosed as
            # a known limitation, not silently faked.
            latitude=0.0,
            longitude=0.0,
            is_active=True,
        )
        db.add(branch)

        temporary_password = TokenService.generate_temporary_password()
        admin_id = f"usr_{uuid.uuid4().hex[:12]}"
        admin_user = User(
            id=admin_id,
            tenant_id=tenant_id,
            role_id=admin_role.id,
            email=req.admin_email,
            phone=req.admin_phone,
            hashed_password=hash_password(temporary_password),
            name=req.admin_name,
            kyc_status="Verified",  # internal staff account, not a customer subject to KYC
            member_since=now.strftime("%B %Y"),
            is_active=True,
        )
        db.add(admin_user)

        # Activation link — a real PasswordResetToken, same table/flow as
        # "forgot password" (see module docstring above).
        raw_activation_token = TokenService.generate_raw_token()
        activation_expires_at = now + timedelta(hours=settings.TENANT_ACTIVATION_TOKEN_EXPIRE_HOURS)
        activation_token = PasswordResetToken(
            id=f"prt_{uuid.uuid4().hex[:16]}",
            user_id=admin_id,
            token_hash=TokenService.hash_token(raw_activation_token),
            expires_at=activation_expires_at,
        )
        db.add(activation_token)

        # A real bug, found via testing: unlike every other audit-log call
        # site in this codebase (which always references an *already*
        # committed tenant_id, e.g. current_user.tenant_id), this is the
        # first place a brand-new Tenant and an AuditLog referencing that
        # same tenant are ever inserted in the same flush. AuditLog.tenant_id
        # is a bare FK column (no mapped `relationship()` to Tenant), so
        # SQLAlchemy's unit-of-work has no object-graph edge to sort on and
        # can batch the 4 audit_log inserts ahead of the tenant insert,
        # violating the FK constraint. An explicit flush here forces every
        # `db.add()`'d row above to actually hit the DB (with real rows
        # present to reference) before the audit log inserts are built —
        # still inside the same uncommitted transaction, so the "all or
        # nothing" rollback guarantee described in this method's docstring
        # is unaffected: a failure here still rolls back everything via
        # get_async_db's exception handler, nothing commits early.
        await db.flush()

        # ── Audit log every step (append-only, same writer as every other module) ──
        for action, target_entity, target_id, after_state in (
            ("TENANT_CREATE", "tenants", tenant_id, {"name": req.business_name, "slug": subdomain}),
            ("SUBSCRIPTION_CREATE", "subscriptions", subscription_id, {"plan": req.plan, "tenant_id": tenant_id}),
            ("BRANCH_CREATE", "branches", branch_id, {"name": branch.name, "tenant_id": tenant_id}),
            ("TENANT_ADMIN_CREATE", "users", admin_id, {"email": req.admin_email, "tenant_id": tenant_id}),
        ):
            await AuditRepository.create_log(
                db,
                tenant_id=tenant_id,
                actor_user_id=current_user.id,
                actor_name=current_user.name,
                actor_role=current_user.role.name,
                action=action,
                target_entity=target_entity,
                target_id=target_id,
                before_state=None,
                after_state=after_state,
            )

        await db.commit()
        await db.refresh(tenant)

        # ── Onboarding email — best-effort, outside the transaction (see docstring) ──
        activation_link = f"{settings.FRONTEND_URL}/auth/reset-password?token={raw_activation_token}"
        onboarding_email_sent = False
        if req.admin_email:
            try:
                await get_email_provider().send_email(
                    to=req.admin_email,
                    subject=f"Welcome to DFX Solution — {req.business_name} is ready",
                    body_text=(
                        f"Hi {req.admin_name},\n\n"
                        f"Your DFX Solution workspace for {req.business_name} has been created.\n\n"
                        f"Before you sign in, set your own password using this link (expires in "
                        f"{settings.TENANT_ACTIVATION_TOKEN_EXPIRE_HOURS} hours, single use):\n\n"
                        f"{activation_link}\n\n"
                        f"Your login email is: {req.admin_email}\n\n"
                        f"If the link expires, use \"Forgot Password\" on the login page with this same email."
                    ),
                    body_html=(
                        f"<p>Hi {req.admin_name},</p>"
                        f"<p>Your DFX Solution workspace for <strong>{req.business_name}</strong> has been created.</p>"
                        f"<p>Before you sign in, set your own password using this link (expires in "
                        f"{settings.TENANT_ACTIVATION_TOKEN_EXPIRE_HOURS} hours, single use):</p>"
                        f'<p><a href="{activation_link}">{activation_link}</a></p>'
                        f"<p>Your login email is: {req.admin_email}</p>"
                        f'<p>If the link expires, use "Forgot Password" on the login page with this same email.</p>'
                    ),
                )
                onboarding_email_sent = True
            except Exception as e:
                # Never never log the temporary password — this email
                # intentionally does not contain it (see the response's
                # `temporary_password` field docstring). Only the send
                # failure itself is logged.
                logger.warning(f"Could not send onboarding email to new admin '{admin_id}': {e}")

        admin = await SuperAdminRepository.get_primary_admin_for_tenant(db, tenant_id)
        return TenantProvisionResponse(
            tenant=TenantDetailResponse(
                id=tenant.id,
                name=tenant.name,
                slug=tenant.slug,
                status=tenant.status,
                brand_color=tenant.brand_color,
                logo_url=tenant.logo_url,
                created_at=tenant.created_at,
                updated_at=tenant.updated_at,
                **_admin_contact_fields(admin),
            ),
            branch=BranchSummary.model_validate(branch),
            subscription=SubscriptionSummary.model_validate(subscription),
            admin=ProvisionedAdminSummary.model_validate(admin_user),
            temporary_password=temporary_password,
            activation_link=activation_link,
            activation_link_expires_at=activation_expires_at,
            onboarding_email_sent=onboarding_email_sent,
        )

    @staticmethod
    async def get_tenant_statistics(
        db: AsyncSession,
        current_user: User,
        tenant_id: str,
        period: Optional[str],
        date_from: Optional[date],
        date_to: Optional[date],
    ) -> TenantStatisticsResponse:
        tenant = await SuperAdminRepository.get_tenant_by_id(db, tenant_id)
        if not tenant:
            raise ResourceNotFoundException(f"Tenant ID '{tenant_id}' not found")

        d_from, d_to, label = _resolve_range(period, date_from, date_to)

        # Reuses Module 12's ReportRepository directly against the *target*
        # tenant_id (never current_user.tenant_id) — cross-tenant aggregation
        # for a SuperAdmin viewer, zero duplicated SQL.
        payment_totals = await ReportRepository.get_payment_totals(db, tenant_id, d_from, d_to)
        status_counts = await ReportRepository.get_enrollment_status_counts(db, tenant_id)
        customer_count = await ReportRepository.get_customer_count(db, tenant_id, as_of=None)
        gold = await ReportRepository.get_gold_accumulation_total(db, tenant_id, d_from, d_to)
        scheme_rows = await ReportRepository.get_scheme_summary(db, tenant_id, d_from, d_to)

        return TenantStatisticsResponse(
            tenant_id=tenant.id,
            tenant_name=tenant.name,
            range=DateRangeInfo(date_from=d_from, date_to=d_to, label=label),
            total_customers=customer_count,
            active_enrollments=status_counts[STATUS_ACTIVE],
            completed_enrollments=status_counts[STATUS_COMPLETED],
            cancelled_enrollments=status_counts[STATUS_CANCELLED],
            total_revenue=payment_totals["success_amount"],
            outstanding_dues=payment_totals["pending_amount"],
            total_gold_accumulated_grams=gold["total_gold_weight_grams"],
            active_schemes=sum(1 for s in scheme_rows if s["is_active"]),
        )

    # ─── Platform Dashboard ───

    @staticmethod
    async def get_platform_dashboard(
        db: AsyncSession,
        current_user: User,
        period: Optional[str],
        date_from: Optional[date],
        date_to: Optional[date],
    ) -> PlatformDashboardResponse:
        d_from, d_to, label = _resolve_range(period, date_from, date_to)

        status_counts = await SuperAdminRepository.get_tenant_status_counts(db)
        total_tenants = sum(c["count"] for c in status_counts)
        active_tenants = next((c["count"] for c in status_counts if c["status"] == "Active"), 0)

        entity_counts = await SuperAdminRepository.get_platform_entity_counts(db)

        group_by_month = (d_to - d_from).days > 31
        growth_rows = await SuperAdminRepository.get_tenant_growth_trend(db, d_from, d_to, group_by_month)

        recent_tenants = await SuperAdminRepository.get_tenants(db, status_filter=None, limit=8)

        return PlatformDashboardResponse(
            range=DateRangeInfo(date_from=d_from, date_to=d_to, label=label),
            total_tenants=total_tenants,
            active_tenants=active_tenants,
            total_customers=entity_counts["total_customers"],
            total_schemes=entity_counts["total_schemes"],
            total_enrollments=entity_counts["total_enrollments"],
            total_payments=entity_counts["total_payments"],
            total_payment_amount=entity_counts["total_payment_amount"],
            growth_trend=[
                PlatformGrowthPoint(
                    period_label=_label_bucket(row["bucket"], group_by_month),
                    new_tenants=row["new_tenants"],
                )
                for row in growth_rows
            ],
            status_breakdown=[TenantStatusBreakdownItem(**c) for c in status_counts],
            recent_tenants=[RecentTenantItem.model_validate(t) for t in recent_tenants],
        )

    # ─── Export (Module 15 — reuses the methods above, no duplicated queries) ───

    @staticmethod
    async def export_platform_dashboard(
        db: AsyncSession,
        current_user: User,
        fmt: ExportFormat,
    ) -> ExportFileResponse:
        """SuperAdmin Dashboard export — the platform-wide KPI snapshot,
        fetched with the same period (this_year) the page itself calls.
        Note: the pre-existing button on this page is labeled "Export Audit
        Report" (leftover copy from before Module 14 relabeled the other 5
        KPI cards) but this page has never displayed audit data — the
        platform-wide audit trail has its own dedicated export on the Audit
        Logs page instead (see AuditService.export_logs). This export is the
        dashboard's own summary data, matching what the page actually shows;
        the button's label was left unchanged per this module's
        no-redesign instruction, flagged here per house style."""
        data = await SuperAdminService.get_platform_dashboard(db, current_user, "this_year", None, None)
        rows = [
            {"metric": "Total Tenants", "value": data.total_tenants},
            {"metric": "Active Tenants", "value": data.active_tenants},
            {"metric": "Total Customers", "value": data.total_customers},
            {"metric": "Total Schemes", "value": data.total_schemes},
            {"metric": "Total Enrollments", "value": data.total_enrollments},
            {"metric": "Total Payments", "value": data.total_payments},
            {"metric": "Total Payment Amount (INR)", "value": data.total_payment_amount},
        ]
        columns = [ExportColumn("metric", "Metric"), ExportColumn("value", "Value")]
        stem = f"DFX_Solution_Platform_Dashboard_{_today_ist().isoformat()}"
        return ExportService.generate(rows, columns, fmt, stem)

    @staticmethod
    async def export_tenants(
        db: AsyncSession,
        current_user: User,
        status_filter: Optional[str],
        fmt: ExportFormat,
    ) -> ExportFileResponse:
        """SuperAdmin Tenants page export — the full tenant list (respecting
        the page's status filter, if any is applied), reusing get_tenants
        exactly as the list view does."""
        tenants = await SuperAdminService.get_tenants(db, current_user, status_filter)
        columns = [
            ExportColumn("id", "Tenant ID"),
            ExportColumn("name", "Name"),
            ExportColumn("slug", "Slug"),
            ExportColumn("status", "Status"),
            ExportColumn("admin_name", "Admin Contact"),
            ExportColumn("admin_email", "Admin Email"),
            ExportColumn("admin_phone", "Admin Phone"),
            ExportColumn("created_at", "Created At"),
        ]
        rows = []
        for t in tenants:
            row = t.model_dump(mode="json")
            for key in ("admin_name", "admin_email", "admin_phone"):
                if row.get(key) is None:
                    row[key] = "—"
            rows.append(row)
        suffix = f"_{status_filter}" if status_filter else ""
        stem = f"DFX_Solution_Tenants{suffix}_{_today_ist().isoformat()}"
        return ExportService.generate(rows, columns, fmt, stem)
