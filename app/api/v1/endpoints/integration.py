from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.models.auth import User
from app.permissions.dependencies import require_superadmin
from app.schemas.auth import StandardSuccessResponse
from app.schemas.integration import IntegrationConfigRequest, IntegrationEnableRequest, WebhookCreateRequest
from app.services.integration_service import IntegrationService

router = APIRouter()


@router.get(
    "/superadmin/integrations",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="List Integrations (SuperAdmin)",
    description="Never returns a raw credential — only enabled/configured/status.",
)
async def list_integrations(
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_async_db),
):
    items = await IntegrationService.list_integrations(db)
    return StandardSuccessResponse(success=True, message="Integrations retrieved successfully", data={"integrations": [i.model_dump(mode="json") for i in items]})


@router.get(
    "/superadmin/integrations/{provider}",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Integration Detail (SuperAdmin)",
)
async def get_integration(
    provider: str,
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_async_db),
):
    item = await IntegrationService.get_integration(db, provider)
    return StandardSuccessResponse(success=True, message="Integration retrieved successfully", data={"integration": item.model_dump(mode="json")})


@router.put(
    "/superadmin/integrations/{provider}/config",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Configure Integration Credentials (SuperAdmin)",
    description="Encrypts and stores provider credentials at rest. Never returns them — the response contains only masked values.",
)
async def configure_integration(
    provider: str,
    req: IntegrationConfigRequest,
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_async_db),
):
    item = await IntegrationService.save_config(db, current_user, provider, req.values)
    return StandardSuccessResponse(success=True, message="Integration configuration saved", data={"integration": item.model_dump(mode="json")})


@router.delete(
    "/superadmin/integrations/{provider}/config",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Remove Integration Configuration (SuperAdmin)",
)
async def remove_integration_config(
    provider: str,
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_async_db),
):
    item = await IntegrationService.clear_config(db, current_user, provider)
    return StandardSuccessResponse(success=True, message="Integration configuration removed", data={"integration": item.model_dump(mode="json")})


@router.put(
    "/superadmin/integrations/{provider}",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Enable/Disable Integration (SuperAdmin)",
    description="Enabling requires the provider's credentials to already be configured via environment variables.",
)
async def set_integration_enabled(
    provider: str,
    req: IntegrationEnableRequest,
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_async_db),
):
    item = await IntegrationService.set_enabled(db, current_user, provider, req.enabled)
    return StandardSuccessResponse(success=True, message="Integration updated successfully", data={"integration": item.model_dump(mode="json")})


@router.post(
    "/superadmin/integrations/{provider}/test",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Test Integration Connection (SuperAdmin)",
    description="Truthfully reports not_configured when no credentials exist — never fakes a successful connection.",
)
async def test_integration(
    provider: str,
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_async_db),
):
    result = await IntegrationService.test_connection(db, current_user, provider)
    return StandardSuccessResponse(success=result.status != "failed", message=result.message, data=result.model_dump(mode="json"))


@router.post(
    "/superadmin/integrations/{provider}/enable",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Enable Integration (SuperAdmin)",
)
async def enable_integration(
    provider: str,
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_async_db),
):
    item = await IntegrationService.set_enabled(db, current_user, provider, True)
    return StandardSuccessResponse(success=True, message="Integration enabled", data={"integration": item.model_dump(mode="json")})


@router.post(
    "/superadmin/integrations/{provider}/disable",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Disable Integration (SuperAdmin)",
)
async def disable_integration(
    provider: str,
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_async_db),
):
    item = await IntegrationService.set_enabled(db, current_user, provider, False)
    return StandardSuccessResponse(success=True, message="Integration disabled", data={"integration": item.model_dump(mode="json")})


# ─── Webhook foundation ───

@router.get(
    "/superadmin/webhooks",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="List Webhooks (SuperAdmin)",
)
async def list_webhooks(
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_async_db),
):
    items = await IntegrationService.list_webhooks(db)
    return StandardSuccessResponse(success=True, message="Webhooks retrieved successfully", data={"webhooks": [i.model_dump(mode="json") for i in items]})


@router.post(
    "/superadmin/webhooks",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Webhook (SuperAdmin)",
    description="The signing secret is returned exactly once, in this response, and never again.",
)
async def create_webhook(
    req: WebhookCreateRequest,
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_async_db),
):
    item = await IntegrationService.create_webhook(db, current_user, req)
    return StandardSuccessResponse(success=True, message="Webhook created — save the signing secret now, it will not be shown again", data={"webhook": item.model_dump(mode="json")})


@router.delete(
    "/superadmin/webhooks/{webhook_id}",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete Webhook (SuperAdmin)",
)
async def delete_webhook(
    webhook_id: str,
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_async_db),
):
    await IntegrationService.delete_webhook(db, current_user, webhook_id)
    return StandardSuccessResponse(success=True, message="Webhook deleted", data={})
