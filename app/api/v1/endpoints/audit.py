from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.models.auth import User
from app.permissions.dependencies import require_superadmin
from app.schemas.auth import StandardSuccessResponse
from app.schemas.export import ExportFormat
from app.services.audit_service import AuditService

router = APIRouter()


@router.get(
    "/audit-logs",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="List Audit Logs (SuperAdmin)",
    description="Platform-wide, paginated, filterable view of the append-only audit trail. Read-only — does not affect how audit entries are written.",
)
async def list_audit_logs(
    tenant_id: Optional[str] = Query(None, description="Filter to a single tenant's logs"),
    actor_role: Optional[str] = Query(None, description="e.g. Admin, Customer, SuperAdmin"),
    target_entity: Optional[str] = Query(None, description="e.g. payments, kyc_records, schemes, tenants"),
    action: Optional[str] = Query(None, description="e.g. KYC_APPROVE, PAYMENT_CREATE_MANUAL"),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_async_db),
):
    result = await AuditService.list_logs(
        db, current_user, tenant_id, actor_role, target_entity, action, date_from, date_to, page, page_size
    )
    return StandardSuccessResponse(
        success=True,
        message="Audit logs retrieved successfully",
        data={"audit_logs": result.model_dump(mode="json")},
    )


# ─── Export (Module 15) ───
# Reusable export infrastructure — see app/services/export_service.py.
# Reuses AuditRepository.list_logs (via AuditService.export_logs) with the
# same structured filters as the endpoint above, just unpaginated up to
# AuditService.EXPORT_MAX_ROWS — no separate/duplicated query.

@router.get(
    "/audit-logs/export",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Export Audit Logs (SuperAdmin)",
    description="Downloadable audit log export (up to the newest 5000 matching rows) as CSV, Excel, or Markdown, using the same module/role/date filters as the list endpoint. Feeds the Audit Logs page's Export button.",
)
async def export_audit_logs(
    format: ExportFormat = Query("excel"),
    tenant_id: Optional[str] = Query(None, description="Filter to a single tenant's logs"),
    actor_role: Optional[str] = Query(None, description="e.g. Admin, Customer, SuperAdmin"),
    target_entity: Optional[str] = Query(None, description="e.g. payments, kyc_records, schemes, tenants"),
    action: Optional[str] = Query(None, description="e.g. KYC_APPROVE, PAYMENT_CREATE_MANUAL"),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_async_db),
):
    file = await AuditService.export_logs(
        db, current_user, tenant_id, actor_role, target_entity, action, date_from, date_to, format
    )
    return StandardSuccessResponse(
        success=True,
        message="Export generated successfully",
        data={"export": file.model_dump(mode="json")},
    )
