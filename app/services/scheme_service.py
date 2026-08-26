import uuid
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.models.scheme import Scheme, SchemeTier
from app.repositories.scheme_repository import SchemeRepository
from app.repositories.audit_repository import AuditRepository
from app.exceptions.base import ResourceNotFoundException, ForbiddenException
from app.schemas.scheme import (
    SchemeCreateRequest,
    SchemeUpdateRequest,
    SchemeResponse,
    SchemeTierResponse,
    CustomerSchemeResponse,
)


def _new_tier_id() -> str:
    return f"str_{uuid.uuid4().hex[:12]}"


class SchemeService:
    @staticmethod
    async def get_schemes(db: AsyncSession, current_user: User) -> List[SchemeResponse]:
        """List all schemes (active + inactive) for the admin's tenant."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        schemes = await SchemeRepository.get_schemes_by_tenant(db, current_user.tenant_id)
        return [SchemeResponse.model_validate(s) for s in schemes]

    @staticmethod
    async def get_scheme_by_id(
        db: AsyncSession, current_user: User, scheme_id: str
    ) -> SchemeResponse:
        """Fetch a single scheme by ID, scoped to the admin's tenant."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        scheme = await SchemeRepository.get_scheme_by_id(db, scheme_id, current_user.tenant_id)
        if not scheme:
            raise ResourceNotFoundException(f"Scheme ID '{scheme_id}' not found")
        return SchemeResponse.model_validate(scheme)

    @staticmethod
    async def create_scheme(
        db: AsyncSession, current_user: User, req: SchemeCreateRequest
    ) -> SchemeResponse:
        """Create a new scheme template for the admin's tenant."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        scheme_id = f"sch_{uuid.uuid4().hex[:12]}"
        scheme = Scheme(
            id=scheme_id,
            tenant_id=current_user.tenant_id,
            name=req.name,
            description=req.description,
            monthly_amount=req.monthly_amount,
            duration_months=req.duration_months,
            bonus_description=req.bonus_description,
            is_active=True,
            created_by=current_user.id,
        )
        await SchemeRepository.create_scheme(db, scheme)

        # Optional selectable tiers. Duplicate (amount, duration) combos are
        # already rejected by the request validator; the DB unique constraint is
        # the backstop.
        if req.tiers:
            for t in req.tiers:
                db.add(SchemeTier(
                    id=_new_tier_id(),
                    scheme_id=scheme_id,
                    monthly_amount=t.monthly_amount,
                    duration_months=t.duration_months,
                    is_active=t.is_active,
                ))

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="SCHEME_CREATE",
            target_entity="schemes",
            target_id=scheme_id,
            before_state=None,
            after_state={
                "name": req.name,
                "monthly_amount": req.monthly_amount,
                "duration_months": req.duration_months,
                "tiers": [
                    {"monthly_amount": t.monthly_amount, "duration_months": t.duration_months,
                     "is_active": t.is_active}
                    for t in (req.tiers or [])
                ],
            },
        )

        await db.commit()
        # Re-fetch with tiers eagerly loaded (the created scheme instance's tier
        # collection is not populated after commit in async).
        created = await SchemeRepository.get_scheme_by_id(db, scheme_id, current_user.tenant_id)
        return SchemeResponse.model_validate(created)

    @staticmethod
    async def update_scheme(
        db: AsyncSession, current_user: User, scheme_id: str, req: SchemeUpdateRequest
    ) -> SchemeResponse:
        """Update an existing scheme's fields (including reactivating via is_active)."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        scheme = await SchemeRepository.get_scheme_by_id(db, scheme_id, current_user.tenant_id)
        if not scheme:
            raise ResourceNotFoundException(f"Scheme ID '{scheme_id}' not found")

        before_state = {
            "name": scheme.name,
            "monthly_amount": scheme.monthly_amount,
            "duration_months": scheme.duration_months,
            "is_active": scheme.is_active,
        }

        for field in ["name", "description", "monthly_amount", "duration_months", "bonus_description", "is_active"]:
            val = getattr(req, field, None)
            if val is not None:
                setattr(scheme, field, val)

        # Tier reconciliation (only when a tiers array is supplied). Existing
        # tiers are matched by their (monthly_amount, duration_months) identity:
        #   - a matching tier keeps its row and takes the supplied is_active,
        #   - a brand-new combo is added,
        #   - an existing tier absent from the list is DEACTIVATED, never deleted,
        #     so enrollments that reference it keep working and history is kept.
        # Existing enrollments are untouched regardless — they carry their own
        # snapshot — so this only ever changes what NEW enrollments may select.
        tier_changes = None
        if req.tiers is not None:
            existing = {(t.monthly_amount, t.duration_months): t for t in scheme.tiers}
            wanted = set()
            added = []
            for t in req.tiers:
                key = (t.monthly_amount, t.duration_months)
                wanted.add(key)
                if key in existing:
                    existing[key].is_active = t.is_active
                else:
                    db.add(SchemeTier(
                        id=_new_tier_id(),
                        scheme_id=scheme.id,
                        monthly_amount=t.monthly_amount,
                        duration_months=t.duration_months,
                        is_active=t.is_active,
                    ))
                    added.append({"monthly_amount": t.monthly_amount, "duration_months": t.duration_months})
            deactivated = []
            for key, tier in existing.items():
                if key not in wanted and tier.is_active:
                    tier.is_active = False
                    deactivated.append({"monthly_amount": key[0], "duration_months": key[1]})
            tier_changes = {"added": added, "deactivated": deactivated}

        after_state = {
            "name": scheme.name,
            "monthly_amount": scheme.monthly_amount,
            "duration_months": scheme.duration_months,
            "is_active": scheme.is_active,
        }
        if tier_changes is not None:
            after_state["tier_changes"] = tier_changes

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="SCHEME_UPDATE",
            target_entity="schemes",
            target_id=scheme_id,
            before_state=before_state,
            after_state=after_state,
        )

        await db.commit()
        # Re-fetch with tiers eagerly loaded for a consistent response.
        refreshed = await SchemeRepository.get_scheme_by_id(db, scheme_id, current_user.tenant_id)
        return SchemeResponse.model_validate(refreshed)

    @staticmethod
    async def deactivate_scheme(
        db: AsyncSession, current_user: User, scheme_id: str
    ) -> None:
        """Soft-delete a scheme by setting is_active=False. The row is never removed."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        scheme = await SchemeRepository.get_scheme_by_id(db, scheme_id, current_user.tenant_id)
        if not scheme:
            raise ResourceNotFoundException(f"Scheme ID '{scheme_id}' not found")

        scheme.is_active = False

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="SCHEME_DEACTIVATE",
            target_entity="schemes",
            target_id=scheme_id,
            before_state={"is_active": True},
            after_state={"is_active": False},
        )

        await db.commit()

    @staticmethod
    async def get_customer_schemes(
        db: AsyncSession, current_user: User
    ) -> List[CustomerSchemeResponse]:
        """List active-only schemes for the customer's tenant (read-only)."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        schemes = await SchemeRepository.get_schemes_by_tenant(db, current_user.tenant_id, active_only=True)
        # The customer is only offered ACTIVE tiers to select from; inactive tiers
        # stay in the admin grid but never in the customer picker.
        return [
            CustomerSchemeResponse(
                id=s.id,
                name=s.name,
                description=s.description,
                monthly_amount=s.monthly_amount,
                duration_months=s.duration_months,
                bonus_description=s.bonus_description,
                tiers=[SchemeTierResponse.model_validate(t) for t in s.tiers if t.is_active],
            )
            for s in schemes
        ]
