from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.scheme import Scheme


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
