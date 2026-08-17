from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.scheme import Scheme, SchemeRequest, SCHEME_REQUEST_REQUESTED


class SchemeRepository:
    @staticmethod
    async def get_schemes_by_tenant(
        db: AsyncSession, tenant_id: str, active_only: bool = False
    ) -> List[Scheme]:
        stmt = select(Scheme).where(Scheme.tenant_id == tenant_id)
        if active_only:
            stmt = stmt.where(Scheme.is_active == True)
        stmt = stmt.order_by(Scheme.created_at.desc())
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_scheme_by_id(
        db: AsyncSession, scheme_id: str, tenant_id: str
    ) -> Optional[Scheme]:
        stmt = select(Scheme).where(
            Scheme.id == scheme_id,
            Scheme.tenant_id == tenant_id,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def create_scheme(db: AsyncSession, scheme: Scheme) -> Scheme:
        db.add(scheme)
        return scheme


class SchemeRequestRepository:
    """Phase 2 — persistence for the scheme-join request lifecycle. Every read
    is tenant-scoped; a caller can never reach another tenant's request."""

    @staticmethod
    async def create(db: AsyncSession, request: SchemeRequest) -> SchemeRequest:
        db.add(request)
        return request

    @staticmethod
    async def get_by_id_for_update(
        db: AsyncSession, request_id: str, tenant_id: str
    ) -> Optional[SchemeRequest]:
        """Row-locked fetch used by approve/reject so two concurrent approvals
        serialize — the second waits, then sees status != REQUESTED."""
        stmt = (
            select(SchemeRequest)
            .where(SchemeRequest.id == request_id, SchemeRequest.tenant_id == tenant_id)
            .with_for_update()
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_id(
        db: AsyncSession, request_id: str, tenant_id: str
    ) -> Optional[SchemeRequest]:
        stmt = (
            select(SchemeRequest)
            .options(
                joinedload(SchemeRequest.scheme),
                joinedload(SchemeRequest.customer),
                joinedload(SchemeRequest.enrollment),
            )
            .where(SchemeRequest.id == request_id, SchemeRequest.tenant_id == tenant_id)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def list_by_tenant(
        db: AsyncSession, tenant_id: str, status: Optional[str] = None
    ) -> List[SchemeRequest]:
        stmt = (
            select(SchemeRequest)
            .options(
                joinedload(SchemeRequest.scheme),
                joinedload(SchemeRequest.customer),
                joinedload(SchemeRequest.enrollment),
            )
            .where(SchemeRequest.tenant_id == tenant_id)
        )
        if status:
            stmt = stmt.where(SchemeRequest.status == status)
        stmt = stmt.order_by(SchemeRequest.created_at.desc())
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def list_by_customer(
        db: AsyncSession, tenant_id: str, customer_id: str
    ) -> List[SchemeRequest]:
        stmt = (
            select(SchemeRequest)
            .options(
                joinedload(SchemeRequest.scheme),
                joinedload(SchemeRequest.customer),
                joinedload(SchemeRequest.enrollment),
            )
            .where(
                SchemeRequest.tenant_id == tenant_id,
                SchemeRequest.customer_id == customer_id,
            )
            .order_by(SchemeRequest.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_pending_for_scheme(
        db: AsyncSession, tenant_id: str, customer_id: str, scheme_id: str
    ) -> Optional[SchemeRequest]:
        """An open (REQUESTED) request by this customer for this scheme, if any.
        Used to stop a customer stacking duplicate pending requests; a NEW
        request is still allowed once the previous one is APPROVED/REJECTED."""
        stmt = select(SchemeRequest).where(
            SchemeRequest.tenant_id == tenant_id,
            SchemeRequest.customer_id == customer_id,
            SchemeRequest.scheme_id == scheme_id,
            SchemeRequest.status == SCHEME_REQUEST_REQUESTED,
        )
        result = await db.execute(stmt)
        return result.scalars().first()
