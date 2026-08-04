from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.logging import setup_logging, logger
from app.core.database import check_database_connection, close_database_connections
from app.api.v1.router import api_router
from app.exceptions.base import JROSException


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup tasks
    setup_logging()
    logger.info(f"Starting {settings.PROJECT_NAME} (v{settings.VERSION})...")

    # Verify DB connectivity on startup
    db_status = await check_database_connection()
    logger.info(f"Startup Database Status: {db_status}")

    yield

    # Shutdown tasks
    logger.info(f"Shutting down {settings.PROJECT_NAME}...")
    await close_database_connections()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS Middleware
if settings.ALLOWED_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# Security Headers Middleware
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    return response


# Chapter 21 Custom Exception Handler
@app.exception_handler(JROSException)
async def jros_exception_handler(request: Request, exc: JROSException):
    logger.warning(
        f"Handled Exception on {request.method} {request.url.path}: [{exc.code}] {exc.message}"
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "message": exc.message,
            "errors": exc.errors,
        },
    )


# Request Validation Exception Handler
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    formatted_errors = []
    for err in exc.errors():
        field_path = " -> ".join([str(loc) for loc in err.get("loc", []) if loc != "body"])
        formatted_errors.append(
            {
                "code": "VALIDATION_ERROR",
                "message": err.get("msg", "Invalid parameter"),
                **({"field": field_path} if field_path else {}),
            }
        )

    logger.warning(f"Validation Failure on {request.method} {request.url.path}: {formatted_errors}")

    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "success": False,
            "message": "Request validation failed",
            "errors": formatted_errors,
        },
    )


# Global Fallback Exception Handler (Chapter 21 / BR-021-01)
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(
        f"Unhandled Exception on {request.method} {request.url.path}: {exc}",
        exc_info=True,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "message": "An internal server error occurred",
            "errors": [
                {
                    "code": "SERVER_ERROR",
                    "message": (
                        str(exc)
                        if settings.DEBUG
                        else "Something went wrong, please try again later"
                    ),
                }
            ],
        },
    )


# Register API v1 Routers
app.include_router(api_router, prefix=settings.API_V1_STR)

# Module 20 — serves locally-stored catalogue images when Supabase Storage
# isn't configured (see app/services/storage_service.py). Irrelevant once a
# real bucket is set — Supabase serves its own public URLs directly.
_upload_dir = Path(settings.LOCAL_UPLOAD_DIR)
_upload_dir.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(_upload_dir)), name="media")


@app.get("/", include_in_schema=False)
async def root_redirect():
    return {
        "project": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "docs": "/docs",
        "health": f"{settings.API_V1_STR}/health",
    }
