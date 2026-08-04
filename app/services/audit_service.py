import math
from datetime import date
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.repositories.audit_repository import AuditRepository
from app.schemas.audit import AuditLogItem, AuditLogListResponse, PaginationInfo
from app.schemas.export import ExportFileResponse, ExportFormat
from app.services.export_service import ExportService, ExportColumn
from app.services.report_service import _today_ist

# Export pulls up to this many of the newest matching rows in one shot,
# unpaginated — same list_logs() query the paginated viewer uses, just
# called with a larger page_size instead of a second, duplicated query path.
EXPORT_MAX_ROWS = 5000


class AuditService:
    """SuperAdmin-only reads over the append-only audit trail (Module 14).
    Does not write audit logs — every other module's AuditRepository.create_log
    call sites are untouched."""

    @staticmethod
    async def list_logs(
        db: AsyncSession,
        current_user: User,
        tenant_id: Optional[str],
        actor_role: Optional[str],
        target_entity: Optional[str],
        action: Optional[str],
        date_from: Optional[date],
        date_to: Optional[date],
        page: int,
        page_size: int,
    ) -> AuditLogListResponse:
        logs, total = await AuditRepository.list_logs(
            db, tenant_id, actor_role, target_entity, action, date_from, date_to, page, page_size
        )
        total_pages = math.ceil(total / page_size) if total else 0

        return AuditLogListResponse(
            logs=[AuditLogItem.model_validate(log) for log in logs],
            pagination=PaginationInfo(page=page, page_size=page_size, total_items=total, total_pages=total_pages),
        )

    # ─── Export (Module 15 — reuses list_logs, no duplicated query) ───

    @staticmethod
    async def export_logs(
        db: AsyncSession,
        current_user: User,
        tenant_id: Optional[str],
        actor_role: Optional[str],
        target_entity: Optional[str],
        action: Optional[str],
        date_from: Optional[date],
        date_to: Optional[date],
        fmt: ExportFormat,
    ) -> ExportFileResponse:
        """Audit Log page export — same structured filters (module/role/date)
        the page's own filter bar already sends; the free-text search box is
        client-side-only (see SESSION_HANDOFF.md Module 14 — no full-text
        search endpoint exists), so it is intentionally not part of this
        export's parameters, matching the page's own documented behavior."""
        logs, total = await AuditRepository.list_logs(
            db, tenant_id, actor_role, target_entity, action, date_from, date_to, page=1, page_size=EXPORT_MAX_ROWS
        )
        columns = [
            ExportColumn("id", "Log ID"),
            ExportColumn("created_at", "Date/Time (UTC)"),
            ExportColumn("actor_name", "Actor"),
            ExportColumn("actor_role", "Role"),
            ExportColumn("action", "Action"),
            ExportColumn("target_entity", "Module"),
            ExportColumn("target_id", "Target ID"),
            ExportColumn("tenant_id", "Tenant ID"),
        ]
        rows = []
        for log in logs:
            rows.append(
                {
                    "id": log.id,
                    "created_at": log.created_at.isoformat(),
                    "actor_name": log.actor_name,
                    "actor_role": log.actor_role,
                    "action": log.action,
                    "target_entity": log.target_entity,
                    "target_id": log.target_id or "—",
                    "tenant_id": log.tenant_id or "—",
                }
            )
        stem = f"DFX_Solution_Audit_Log_{_today_ist().isoformat()}"
        return ExportService.generate(rows, columns, fmt, stem)
