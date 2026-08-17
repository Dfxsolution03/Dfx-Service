from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.otp import OtpChallenge


class OtpRepository:
    @staticmethod
    async def create(db: AsyncSession, challenge: OtpChallenge) -> OtpChallenge:
        db.add(challenge)
        return challenge

    @staticmethod
    async def expire_active(
        db: AsyncSession, tenant_id: str, customer_id: str, purpose: str, sale_id: Optional[str]
    ) -> None:
        """Kill any still-open challenge for the same (tenant, customer, purpose,
        sale) before issuing a new one, so only the newest code is ever valid —
        a re-request invalidates the previous code."""
        now = datetime.now(timezone.utc)
        stmt = (
            update(OtpChallenge)
            .where(
                OtpChallenge.tenant_id == tenant_id,
                OtpChallenge.customer_id == customer_id,
                OtpChallenge.purpose == purpose,
                OtpChallenge.sale_id == sale_id,
                OtpChallenge.consumed_at.is_(None),
                OtpChallenge.expires_at > now,
            )
            .values(expires_at=now)
        )
        await db.execute(stmt)

    @staticmethod
    async def get_latest_active_for_update(
        db: AsyncSession, tenant_id: str, customer_id: str, purpose: str, sale_id: Optional[str]
    ) -> Optional[OtpChallenge]:
        """Row-locked fetch of the newest unconsumed challenge for verification.
        FOR UPDATE serialises concurrent verifies so one code can be spent once."""
        stmt = (
            select(OtpChallenge)
            .where(
                OtpChallenge.tenant_id == tenant_id,
                OtpChallenge.customer_id == customer_id,
                OtpChallenge.purpose == purpose,
                OtpChallenge.sale_id == sale_id,
                OtpChallenge.consumed_at.is_(None),
            )
            .order_by(OtpChallenge.created_at.desc())
            .limit(1)
            .with_for_update()
        )
        return (await db.execute(stmt)).scalar_one_or_none()
