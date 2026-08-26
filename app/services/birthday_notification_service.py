"""Customer birthday wishes — in-app notification + best-effort push.

A wishes-only engine: it never exposes any commercial value, ranking, or
priority to the customer. "Priority / Complimentary Opportunity" stays an
admin-side Reports concept only (see Reports Analytics); the customer simply
receives a warm, generic birthday message.

Idempotent and safe to run repeatedly: at most one BIRTHDAY notification per
customer per birthday (guarded by NotificationRepository.birthday_notified_since
over the IST day). One notification per customer regardless of whether they are a
business customer, scheme customer, or both — DOB is per-user, not per-domain.

Delivery mirrors the overdue-reminder engine: the in-app row is the durable
record; push is best-effort and reports configured=False (sends nothing, fakes
nothing) when no PUSH_PROVIDER is set.
"""
from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.notification_repository import NotificationRepository
from app.services.notification_service import NotificationService
from app.services.push_service import PushService
from app.services.report_service import _next_birthday_days

_IST = timezone(timedelta(hours=5, minutes=30))

_TITLE = "Happy Birthday!"
_MESSAGE = (
    "Wishing you a very happy birthday and a wonderful year ahead. "
    "Thank you for being a valued member of our family."
)


def _today_ist() -> date:
    return datetime.now(_IST).date()


def _ist_day_start_utc(day: date) -> datetime:
    """Start of the given IST calendar day, as a UTC-aware datetime — the
    lower bound for today's idempotency check."""
    return datetime(day.year, day.month, day.day, tzinfo=_IST).astimezone(timezone.utc)


class BirthdayNotificationService:
    @staticmethod
    async def run_birthday_wishes(
        db: AsyncSession, today: Optional[date] = None, tenant_id: Optional[str] = None
    ) -> dict:
        """Send today's birthday wishes. `today`/`tenant_id` are injectable for
        testing. Returns an honest summary; never fabricates a delivery."""
        run_day = today or _today_ist()
        since = _ist_day_start_utc(run_day)
        customers = await NotificationRepository.list_customers_with_dob(db, tenant_id)

        created = 0
        to_push: list = []
        for c in customers:
            # Birthday today = shared matcher at 0 days (Feb-29 → Feb-28 safe).
            if _next_birthday_days(c["date_of_birth"], run_day, window=1) != 0:
                continue
            if await NotificationRepository.birthday_notified_since(db, c["tenant_id"], c["user_id"], since):
                continue
            await NotificationService.create_notification(
                db,
                tenant_id=c["tenant_id"],
                user_id=c["user_id"],
                title=_TITLE,
                message=_MESSAGE,
                type="BIRTHDAY",
            )
            created += 1
            to_push.append((c["tenant_id"], c["user_id"]))

        await db.commit()

        pushed = 0
        for t_id, u_id in to_push:
            # No commercial data in the push payload — wishes only.
            result = await PushService.send_to_user(
                db, t_id, u_id, title=_TITLE, body=_MESSAGE, data={"type": "BIRTHDAY"}
            )
            if result.get("sent"):
                pushed += result["sent"]

        return {"date": run_day.isoformat(), "created": created, "pushed": pushed}
