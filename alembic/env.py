import asyncio
from logging.config import fileConfig
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context

# Import settings and Base model
from app.core.config import settings
from app.models.base import Base

config = context.config

if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _to_async_url(url: str) -> str:
    """Force the migration URL onto an async driver.

    run_async_migrations() builds an async engine, but .env.example documents
    DIRECT_URL — the connection migrations are supposed to use — as a plain
    `postgresql://` string. SQLAlchemy would then load psycopg2 and raise
    "The asyncio extension requires an async driver to be used". Normalising
    here keeps DIRECT_URL usable exactly as documented.

    Also strips `?pgbouncer=true`, a Prisma-specific flag that .env.example
    carries on the transaction-mode DATABASE_URL; asyncpg rejects it as an
    unknown connect argument. Relevant because migrations fall back to
    DATABASE_URL whenever DIRECT_URL is unset.
    """
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif url.startswith("sqlite://"):
        url = url.replace("sqlite://", "sqlite+aiosqlite://", 1)

    parts = urlsplit(url)
    if "pgbouncer" in parse_qs(parts.query):
        query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if k != "pgbouncer"])
        url = urlunsplit(parts._replace(query=query))
    return url


# Use DIRECT_URL for migrations if defined, otherwise DATABASE_URL
migration_db_url = _to_async_url(settings.DIRECT_URL or settings.DATABASE_URL)
# '%' is the configparser interpolation character and this value reaches the
# engine via config.get_section() — escape it so a password containing '%'
# survives intact.
config.set_main_option("sqlalchemy.url", migration_db_url.replace("%", "%%"))


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations using async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
