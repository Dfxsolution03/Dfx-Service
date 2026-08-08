import uuid
from datetime import date, datetime, timezone, timedelta
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.models.goldrate import GoldRate
from app.repositories.goldrate_repository import GoldRateRepository
from app.repositories.audit_repository import AuditRepository
from app.exceptions.base import ConflictException, ResourceNotFoundException, ForbiddenException
from app.schemas.goldrate import GoldRateCreateRequest, GoldRateUpdateRequest, GoldRateResponse, CustomerGoldRateResponse
from app.services.tenant_pricing_service import TenantPricingService

# JROS is an India-only business (INR, Indian phone formats, IST-centric UX
# throughout) — "today" for a daily gold rate must follow IST, not UTC, or
# the rate would flip over at 5:30 AM IST instead of midnight IST.
# IST has no DST, so a fixed offset is always correct (no tzdata needed).
IST = timezone(timedelta(hours=5, minutes=30))


def _today_ist() -> date:
    return datetime.now(IST).date()


class GoldRateService:
    @staticmethod
    async def get_today_rate(
        db: AsyncSession, current_user: User
    ) -> Optional[GoldRateResponse]:
        """Fetch today's gold rate for the admin's tenant (Admin view)."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        today = _today_ist()
        rate = await GoldRateRepository.get_rate_for_date(db, current_user.tenant_id, today)
        return GoldRateResponse.model_validate(rate) if rate else None

    @staticmethod
    async def create_today_rate(
        db: AsyncSession, current_user: User, req: GoldRateCreateRequest
    ) -> GoldRateResponse:
        """Create today's gold rate. Fails if today's rate already exists."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        today = _today_ist()
        existing = await GoldRateRepository.get_rate_for_date(db, current_user.tenant_id, today)
        if existing:
            raise ConflictException("Today's gold rate has already been set. Use update instead.")

        rate_id = f"gr_{uuid.uuid4().hex[:12]}"
        rate = GoldRate(
            id=rate_id,
            tenant_id=current_user.tenant_id,
            rate_24k=req.rate_24k,
            effective_date=today,
            created_by=current_user.id,
        )
        await GoldRateRepository.create_rate(db, rate)

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="GOLDRATE_CREATE",
            target_entity="gold_rates",
            target_id=rate_id,
            before_state=None,
            after_state={"rate_24k": req.rate_24k, "effective_date": today.isoformat()},
        )

        await db.commit()
        await db.refresh(rate)
        return GoldRateResponse.model_validate(rate)

    @staticmethod
    async def update_today_rate(
        db: AsyncSession, current_user: User, req: GoldRateUpdateRequest
    ) -> GoldRateResponse:
        """Update today's gold rate. Fails if no rate has been set for today yet."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        today = _today_ist()
        rate = await GoldRateRepository.get_rate_for_date(db, current_user.tenant_id, today)
        if not rate:
            raise ResourceNotFoundException("No gold rate has been set for today yet. Create one first.")

        before_state = {"rate_24k": rate.rate_24k}
        rate.rate_24k = req.rate_24k
        rate.created_by = current_user.id
        after_state = {"rate_24k": rate.rate_24k}

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="GOLDRATE_UPDATE",
            target_entity="gold_rates",
            target_id=rate.id,
            before_state=before_state,
            after_state=after_state,
        )

        await db.commit()
        await db.refresh(rate)
        return GoldRateResponse.model_validate(rate)

    @staticmethod
    async def get_customer_today_rate(
        db: AsyncSession, current_user: User
    ) -> Optional[CustomerGoldRateResponse]:
        """
        Fetch today's gold rate for display to the customer (any authenticated
        tenant user). The tenant's own manually-entered rate for today (the
        pre-Module-31 path) always takes precedence when present — a tenant
        Admin who explicitly set today's rate must keep seeing exactly that
        value. Only when no manual rate exists for today do we fall back to
        Module 31's TenantPricingConfig-derived live rate; if that also
        resolves to nothing (no config, no live rate yet), behavior is
        byte-identical to before Phase 2 — None.
        """
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        today = _today_ist()
        rate = await GoldRateRepository.get_rate_for_date(db, current_user.tenant_id, today)
        if rate:
            return CustomerGoldRateResponse.model_validate(rate)

        effective = await TenantPricingService.get_effective_rate(db, current_user.tenant_id)
        if effective is None:
            return None

        return CustomerGoldRateResponse(
            rate_24k=float(effective.gold_24k),
            effective_date=today,
            updated_at=effective.as_of,
            source=effective.source,
            silver_999=float(effective.silver_999) if effective.silver_999 is not None else None,
        )
