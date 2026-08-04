from typing import AsyncGenerator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool, AsyncAdaptedQueuePool
from app.core.config import settings
from app.core.logging import logger

# Configure Engine Parameters based on database dialect
is_sqlite = settings.DATABASE_URL.startswith("sqlite")

engine_kwargs = {
    "echo": settings.DEBUG,
    "future": True,
}

if is_sqlite:
    engine_kwargs["poolclass"] = NullPool
else:
    engine_kwargs["poolclass"] = AsyncAdaptedQueuePool
    engine_kwargs["pool_size"] = settings.DB_POOL_SIZE
    engine_kwargs["max_overflow"] = settings.DB_MAX_OVERFLOW
    engine_kwargs["pool_recycle"] = settings.DB_POOL_RECYCLE
    engine_kwargs["pool_timeout"] = settings.DB_POOL_TIMEOUT
    engine_kwargs["pool_pre_ping"] = True

# Create Async Engine
engine: AsyncEngine = create_async_engine(settings.DATABASE_URL, **engine_kwargs)

# Async Session Factory
AsyncSessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency Injection generator providing an AsyncSession with automatic cleanup.
    """
    async with AsyncSessionFactory() as session:
        try:
            yield session
        except Exception as exc:
            await session.rollback()
            logger.error(f"Database session rollback triggered: {exc}")
            raise
        finally:
            await session.close()


async def check_database_connection() -> dict:
    """
    Performs an async database connectivity ping executing 'SELECT 1'.
    """
    try:
        async with AsyncSessionFactory() as session:
            result = await session.execute(text("SELECT 1"))
            value = result.scalar()
            if value == 1:
                return {"status": "healthy", "database": "connected"}
            else:
                return {"status": "unhealthy", "database": "unexpected_response"}
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return {
            "status": "unhealthy",
            "database": f"error: {str(e)}" if settings.DEBUG else "connection_failed",
        }


async def close_database_connections() -> None:
    """
    Gracefully disposes of all pooled database connections on application shutdown.
    """
    logger.info("Disposing of database engine connections...")
    await engine.dispose()
    logger.info("Database engine connections closed.")
