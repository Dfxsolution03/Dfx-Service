from fastapi import APIRouter, status
from app.core.database import check_database_connection
from app.core.config import settings
from app.schemas.health import HealthResponse

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="API and Database Health Check",
    description="Verifies API operational status and executes an async database connection ping.",
)
async def health_check() -> HealthResponse:
    # Performance: check_database_connection() opens its own session — this
    # endpoint used to also inject an unused `Depends(get_async_db)`,
    # opening a second, never-used session per health check.
    db_health = await check_database_connection()
    is_healthy = db_health.get("status") == "healthy"

    return HealthResponse(
        success=is_healthy,
        message=(
            "DFX Solution Backend API & Database are operational"
            if is_healthy
            else "Database connectivity issue detected"
        ),
        data={
            "environment": settings.ENVIRONMENT,
            "version": settings.VERSION,
            "database": db_health,
        },
        meta={"debug": settings.DEBUG},
    )
