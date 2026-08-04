import uuid
import json
from datetime import date, datetime, time, timezone
from typing import List, Optional, Any, Tuple
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.audit import AuditLog


class AuditRepository:
    @staticmethod
    async def create_log(
        db: AsyncSession,
        tenant_id: Optional[str],
        actor_user_id: str,
        actor_name: str,
        actor_role: str,
        action: str,
        target_entity: str,
        target_id: Optional[str] = None,
        before_state: Optional[Any] = None,
        after_state: Optional[Any] = None,
    ) -> AuditLog:
        """Create an append-only audit log entry."""
        log_id = f"aud_{uuid.uuid4().hex[:16]}"
        before_str = json.dumps(before_state, default=str) if before_state else None
        after_str = json.dumps(after_state, default=str) if after_state else None

        audit_entry = AuditLog(
            id=log_id,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            actor_name=actor_name,
            actor_role=actor_role,
            action=action,
            target_entity=target_entity,
            target_id=target_id,
            before_state=before_str,
            after_state=after_str,
        )
        db.add(audit_entry)
        # Note: caller will commit transaction
        return audit_entry

    # ─── Reads (Module 14 — SuperAdmin Audit Log viewer) ───
    # Does not change write behavior above in any way; append-only writes are
    # untouched.

    @staticmethod
    async def list_logs(
        db: AsyncSession,
        tenant_id: Optional[str],
        actor_role: Optional[str],
        target_entity: Optional[str],
        action: Optional[str],
        date_from: Optional[date],
        date_to: Optional[date],
        page: int,
        page_size: int,
    ) -> Tuple[List[AuditLog], int]:
        """Paginated, filtered read of the append-only audit trail, newest first.
        No tenant scoping is applied by default (platform-wide view) — pass
        tenant_id to narrow to one tenant."""
        conditions = []
        if tenant_id:
            conditions.append(AuditLog.tenant_id == tenant_id)
        if actor_role:
            conditions.append(AuditLog.actor_role == actor_role)
        if target_entity:
            conditions.append(AuditLog.target_entity == target_entity)
        if action:
            conditions.append(AuditLog.action == action)
        if date_from:
            conditions.append(AuditLog.created_at >= datetime.combine(date_from, time.min, tzinfo=timezone.utc))
        if date_to:
            conditions.append(AuditLog.created_at <= datetime.combine(date_to, time.max, tzinfo=timezone.utc))

        count_stmt = select(func.count(AuditLog.id))
        list_stmt = select(AuditLog).order_by(AuditLog.created_at.desc())
        for cond in conditions:
            count_stmt = count_stmt.where(cond)
            list_stmt = list_stmt.where(cond)

        total = (await db.execute(count_stmt)).scalar_one()
        list_stmt = list_stmt.offset((page - 1) * page_size).limit(page_size)
        rows = (await db.execute(list_stmt)).scalars().all()
        return list(rows), int(total)
