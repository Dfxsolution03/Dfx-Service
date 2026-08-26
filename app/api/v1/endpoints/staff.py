from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.models.auth import User
from app.permissions.dependencies import require_admin_only
from app.schemas.auth import StandardSuccessResponse
from app.schemas.staff import StaffCreateRequest, StaffStatusUpdateRequest, StaffPermissionsUpdateRequest
from app.services.staff_service import StaffService

router = APIRouter()


@router.get(
    "/admin/staff/permission-catalog",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Staff Permission Catalog — Scheme/Business groups (Admin)",
    description="Returns the staff permission modules grouped into Scheme and Business for the two "
                "assignment dropdowns, plus the flat list of valid module keys. Grouping is over the "
                "existing permission keys — assignment still validates against these same keys.",
)
async def get_permission_catalog(
    current_user: User = Depends(require_admin_only),
):
    catalog = StaffService.get_permission_catalog()
    return StandardSuccessResponse(
        success=True,
        message="Permission catalog retrieved successfully",
        data=catalog.model_dump(mode="json"),
    )


@router.get(
    "/admin/staff",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="List Staff (Admin)",
    description="Lists all Staff-role users under the admin's own tenant.",
)
async def list_staff(
    current_user: User = Depends(require_admin_only),
    db: AsyncSession = Depends(get_async_db),
):
    staff = await StaffService.list_staff(db, current_user)
    return StandardSuccessResponse(
        success=True,
        message="Staff retrieved successfully",
        data={"staff": [s.model_dump(mode="json") for s in staff]},
    )


@router.post(
    "/admin/staff",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Staff (Admin)",
    description="Creates a new Staff-role user under the admin's own tenant. Always Staff role — never Admin or SuperAdmin.",
)
async def create_staff(
    req: StaffCreateRequest,
    current_user: User = Depends(require_admin_only),
    db: AsyncSession = Depends(get_async_db),
):
    staff = await StaffService.create_staff(db, current_user, req)
    return StandardSuccessResponse(
        success=True,
        message="Staff member created successfully",
        data={"staff": staff.model_dump(mode="json")},
    )


@router.put(
    "/admin/staff/{staff_id}/status",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Activate / Deactivate Staff (Admin)",
    description="Sets a Staff member's active status. Own-tenant only.",
)
async def update_staff_status(
    staff_id: str,
    req: StaffStatusUpdateRequest,
    current_user: User = Depends(require_admin_only),
    db: AsyncSession = Depends(get_async_db),
):
    staff = await StaffService.update_staff_status(db, current_user, staff_id, req)
    return StandardSuccessResponse(
        success=True,
        message="Staff status updated successfully",
        data={"staff": staff.model_dump(mode="json")},
    )


@router.put(
    "/admin/staff/{staff_id}/permissions",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Staff Module Permissions (Admin)",
    description="Sets the exact set of admin-panel modules a Staff member can access. Own-tenant only. Replaces the full grant set — not additive.",
)
async def update_staff_permissions(
    staff_id: str,
    req: StaffPermissionsUpdateRequest,
    current_user: User = Depends(require_admin_only),
    db: AsyncSession = Depends(get_async_db),
):
    staff = await StaffService.update_staff_permissions(db, current_user, staff_id, req)
    return StandardSuccessResponse(
        success=True,
        message="Staff permissions updated successfully",
        data={"staff": staff.model_dump(mode="json")},
    )
