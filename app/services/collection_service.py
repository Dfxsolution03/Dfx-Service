"""Phase 7 — overdue scheme-contribution reminders.

A reminder-only engine: it never records money and never fabricates a payment
or passbook entry. Overdue is derived from the Phase 3 next_due_date; a
successful contribution advances that date, so the period stops being overdue
and no further reminder is raised (payment stops reminders automatically).

Delivery is IN_APP via the existing Notification infrastructure. WhatsApp/voice
are intentionally NOT wired — no external delivery is claimed or faked.

The engine is safe to run repeatedly and concurrently: each reminder is a row
with a UNIQUE(enrollment_id, due_date), so a duplicate or parallel run that
tries to remind the same period loses the insert race and is skipped, never
double-notifying the customer.
"""
import uuid
from datetime import date, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.models.collection import CollectionReminder, REMINDER_CHANNEL_IN_APP
from app.repositories.collection_repository import CollectionRepository
from app.repositories.audit_repository import AuditRepository
from app.services.notification_service import NotificationService

REMINDER_WINDOW_DAYS = 15  # remind only while 1..15 days overdue


class CollectionService:
    @staticmethod
    async def run_due_reminders(
        db: AsyncSession, today: date | None = None, tenant_id: str | None = None
    ) -> dict:
        """Raise one reminder per overdue (enrollment, due_date) not already
        reminded. Returns a small summary. today is injectable for testing."""
        run_day = today or date.today()
        candidates = await CollectionRepository.list_overdue_active(
            db, run_day, REMINDER_WINDOW_DAYS, tenant_id
        )

        sent, skipped = 0, 0
        for e in candidates:
            due = e.next_due_date
            overdue_days = (run_day - due).days
            reminder = CollectionReminder(
                id=f"col_{uuid.uuid4().hex[:12]}",
                tenant_id=e.tenant_id,
                enrollment_id=e.id,
                customer_id=e.customer_id,
                due_date=due,
                overdue_days=overdue_days,
                channel=REMINDER_CHANNEL_IN_APP,
            )
            # Savepoint per reminder: a UNIQUE collision (already reminded, or a
            # concurrent run) rolls back only this one and the loop continues.
            try:
                async with db.begin_nested():
                    await CollectionRepository.create(db, reminder)
                    await db.flush()
            except IntegrityError:
                skipped += 1
                continue

            await NotificationService.create_notification(
                db,
                tenant_id=e.tenant_id,
                user_id=e.customer_id,
                title="Scheme payment overdue",
                message=(
                    f"Your scheme {e.enrollment_number} installment due on "
                    f"{due.isoformat()} is {overdue_days} day(s) overdue. Please pay "
                    f"at the store or through the app to keep your scheme active."
                ),
                type="PAYMENT",
            )
            await AuditRepository.create_log(
                db, tenant_id=e.tenant_id, actor_user_id=e.customer_id,
                actor_name="system", actor_role="SYSTEM",
                action="COLLECTION_REMINDER", target_entity="collection_reminders",
                target_id=reminder.id, before_state=None,
                after_state={"enrollment_id": e.id, "due_date": due.isoformat(), "overdue_days": overdue_days},
            )
            sent += 1

        await db.commit()
        return {"sent": sent, "skipped": skipped, "candidates": len(candidates)}


# ─── Phase 7 read API — Collections list (read-only) ───
from sqlalchemy import select as _select, func as _func  # noqa: E402
from app.models.scheme import Scheme as _Scheme  # noqa: E402
from app.models.auth import User as _User  # noqa: E402
from app.models.collection import CollectionReminder as _Reminder  # noqa: E402


class CollectionsReadService:
    @staticmethod
    async def list_collections(db: AsyncSession, current_user: User) -> list:
        """Read-only view of currently-overdue scheme installments (1..15 days,
        ACTIVE only — same rule as the reminder engine). Composition only: it
        creates nothing, and reminder counts come from the append-only
        CollectionReminder rows, never a fabricated activity."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        t = current_user.tenant_id
        today = date.today()

        rows = await CollectionRepository.list_overdue_active(db, today, REMINDER_WINDOW_DAYS, t)
        if not rows:
            return []

        enr_ids = [e.id for e in rows]
        scheme_ids = list({e.scheme_id for e in rows})
        cust_ids = list({e.customer_id for e in rows})

        schemes = {s.id: s.name for s in (await db.execute(
            _select(_Scheme.id, _Scheme.name).where(_Scheme.id.in_(scheme_ids))
        )).all()}
        users = {u.id: (u.name, u.phone, u.customer_code) for u in (await db.execute(
            _select(_User.id, _User.name, _User.phone, _User.customer_code).where(_User.id.in_(cust_ids))
        )).all()}
        counts = dict((await db.execute(
            _select(_Reminder.enrollment_id, _func.count(_Reminder.id))
            .where(_Reminder.tenant_id == t, _Reminder.enrollment_id.in_(enr_ids))
            .group_by(_Reminder.enrollment_id)
        )).all())

        out = []
        for e in rows:
            name, phone, code = users.get(e.customer_id, (None, None, None))
            out.append({
                "enrollment_id": e.id,
                "enrollment_number": e.enrollment_number,
                "customer_id": e.customer_id,
                "customer_name": name,
                "customer_code": code,
                "customer_phone": phone,
                "scheme_name": schemes.get(e.scheme_id),
                "due_date": e.next_due_date.isoformat() if e.next_due_date else None,
                "overdue_days": (today - e.next_due_date).days if e.next_due_date else None,
                "reminders_sent": int(counts.get(e.id, 0)),
                "status": "OVERDUE",
            })
        out.sort(key=lambda x: x["overdue_days"] or 0, reverse=True)
        return out
