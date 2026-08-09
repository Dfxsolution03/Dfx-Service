"""
JROS Test Suite — conftest.py
==============================

Central pytest fixtures for the entire JROS test suite.

Design:
- Runs against an ISOLATED test database (TEST_DATABASE_URL) — never against
  DATABASE_URL, which is whatever database the running application (dev,
  staging, or production) is actually using. See _resolve_test_database_url()
  below: pytest refuses to even start collecting tests if TEST_DATABASE_URL
  isn't set, or if it's identical to DATABASE_URL.
- Every test run creates uniquely-named test data (uuid-tagged) to prevent
  collisions with existing records
- Cleanup is performed via finalizers where practical — but the real safety
  guarantee is database isolation, not per-test cleanup discipline (several
  tests predating this guard created rows with no teardown at all).
- All tests are isolated by design (each test creates its own data)
- The JROS FastAPI app is tested through httpx.AsyncClient (real HTTP layer)

Fixtures provided:
- client            → httpx.AsyncClient bound to the JROS app
- db_session        → real AsyncSession against the isolated test database
- test_tenant       → a live Tenant row (seeded at test time)
- customer_token    → JWT pair for a freshly-registered test customer
- customer_user     → the User model object for the test customer
- superadmin_token  → JWT pair for the SuperAdmin (from seed data)
- auth_headers      → Authorization header dict for a given token
"""

import os
import sys
import uuid
import pytest
import pytest_asyncio
from typing import AsyncGenerator, Dict
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.core.database import AsyncSessionFactory
from app.core.security import hash_password, create_access_token, create_refresh_token
from app.core.config import settings
from app.core.constants import ROLE_CUSTOMER, ROLE_ADMIN, ROLE_SUPERADMIN
from app.models.auth import Tenant, Role, User, RefreshToken

# Use NullPool for test sessions — prevents asyncpg "Event loop is closed"
# errors during fixture teardown caused by connection pool cleanup
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession as _AsyncSession
from sqlalchemy.pool import NullPool


def _resolve_test_database_url() -> str:
    """
    Refuses to run any test if there's a real risk of touching a non-test
    database. This is the ONLY thing standing between `pytest` and writing
    directly into production — see the Phase-4/6/7 incident where the lack
    of this check let dozens of tnt_test_*/"Provision Test Co"/"Other Tenant"
    rows accumulate in the live production database.

    Checked in order:
      1. TEST_DATABASE_URL (env var or .env) must be set at all.
      2. It must not be identical to DATABASE_URL — the two must be
         different databases, full stop.
    """
    test_url = os.environ.get("TEST_DATABASE_URL") or settings.TEST_DATABASE_URL
    if not test_url:
        raise RuntimeError(
            "\n\n"
            "REFUSING TO RUN TESTS: TEST_DATABASE_URL is not set.\n"
            "tests/conftest.py will not fall back to DATABASE_URL — that may be "
            "a shared dev database or, worse, production.\n"
            "Set TEST_DATABASE_URL to a separate, isolated Postgres database "
            "(see .env.example) before running pytest.\n"
        )
    if test_url == settings.DATABASE_URL:
        raise RuntimeError(
            "\n\n"
            "REFUSING TO RUN TESTS: TEST_DATABASE_URL is identical to DATABASE_URL.\n"
            "Tests must run against a database that is NOT the one the "
            "application itself uses. Point TEST_DATABASE_URL at a separate "
            "database.\n"
        )
    return test_url


_TEST_DATABASE_URL = _resolve_test_database_url()

_test_engine = create_async_engine(
    _TEST_DATABASE_URL,
    poolclass=NullPool,
    echo=False,
    future=True,
)
_TestSessionFactory = async_sessionmaker(
    bind=_test_engine,
    class_=_AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)



# ─────────────────────────────────────────────
# Suppress asyncpg pool teardown warnings
# These appear when the test event loop ends while the global
# production engine's pool tries to close SSL connections.
# The tests themselves pass — this is cosmetic infrastructure noise.
# ─────────────────────────────────────────────



@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Provides a real AsyncSession connected to Supabase PostgreSQL.
    Uses NullPool (no connection pooling) to prevent event loop teardown errors.
    Each test function gets its own session.
    """
    async with _TestSessionFactory() as session:
        yield session


# ─────────────────────────────────────────────
# HTTP Client
# ─────────────────────────────────────────────

@pytest_asyncio.fixture(scope="function")
async def client() -> AsyncGenerator[AsyncClient, None]:
    """
    httpx.AsyncClient wired directly to the JROS ASGI app.
    
    Overrides `get_async_db` dependency with the NullPool test engine
    to prevent the production connection pool from being used in tests.
    This also eliminates 'Event loop is closed' teardown errors caused
    by the production pool's asyncpg SSL connection cleanup.
    """
    from app.core.database import get_async_db

    async def override_get_async_db():
        async with _TestSessionFactory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    app.dependency_overrides[get_async_db] = override_get_async_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


# ─────────────────────────────────────────────
# Test Tenant
# ─────────────────────────────────────────────

@pytest_asyncio.fixture(scope="function")
async def test_tenant(db_session: AsyncSession) -> Tenant:
    """
    Creates a uniquely-named Tenant row in Supabase for test isolation.
    Deleted after the test completes.
    """
    uid = uuid.uuid4().hex[:8]
    tenant = Tenant(
        id=f"tnt_test_{uid}",
        name=f"Test Jewellery Store {uid}",
        slug=f"test-store-{uid}",
        status="Active",
    )
    db_session.add(tenant)
    await db_session.commit()

    yield tenant

    # Cleanup: remove any users created under this tenant first
    await db_session.execute(
        delete(RefreshToken).where(
            RefreshToken.user_id.in_(
                select(User.id).where(User.tenant_id == tenant.id)
            )
        )
    )
    await db_session.execute(
        delete(User).where(User.tenant_id == tenant.id)
    )
    await db_session.execute(
        delete(Tenant).where(Tenant.id == tenant.id)
    )
    await db_session.commit()


# ─────────────────────────────────────────────
# Customer User + Token
# ─────────────────────────────────────────────

@pytest_asyncio.fixture(scope="function")
async def customer_user(db_session: AsyncSession, test_tenant: Tenant) -> User:
    """
    Creates a test Customer user bound to test_tenant.
    Includes eager-loaded role for JWT token generation.
    """
    uid = uuid.uuid4().hex[:8]

    # Fetch Customer role
    stmt = select(Role).where(Role.name == ROLE_CUSTOMER)
    role = (await db_session.execute(stmt)).scalar_one()

    user = User(
        id=f"usr_test_{uid}",
        tenant_id=test_tenant.id,
        role_id=role.id,
        email=f"testcustomer_{uid}@jros-test.com",
        phone=None,
        hashed_password=hash_password("TestPass@123"),
        name=f"Test Customer {uid}",
        kyc_status="Pending",
        member_since="July 2026",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()

    # Re-fetch with role relationship
    from sqlalchemy.orm import selectinload
    stmt2 = select(User).options(selectinload(User.role)).where(User.id == user.id)
    user_loaded = (await db_session.execute(stmt2)).scalar_one()
    return user_loaded


@pytest.fixture(scope="function")
def customer_token(customer_user: User) -> Dict[str, str]:
    """
    Returns a valid JWT access + refresh token pair for the test customer.
    """
    token_id = f"tkn_test_{uuid.uuid4().hex[:12]}"
    access = create_access_token(
        subject=customer_user.id,
        tenant_id=customer_user.tenant_id,
        role=ROLE_CUSTOMER,
    )
    refresh = create_refresh_token(
        subject=customer_user.id,
        tenant_id=customer_user.tenant_id,
        token_id=token_id,
    )
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_id": token_id,
    }


@pytest.fixture(scope="function")
def customer_auth_headers(customer_token: Dict[str, str]) -> Dict[str, str]:
    """Authorization header dict for test customer."""
    return {"Authorization": f"Bearer {customer_token['access_token']}"}


# ─────────────────────────────────────────────
# Admin User + Token
# ─────────────────────────────────────────────

@pytest_asyncio.fixture(scope="function")
async def admin_user(db_session: AsyncSession, test_tenant: Tenant) -> User:
    """
    Creates a test Admin user bound to test_tenant.
    Includes eager-loaded role for JWT token generation.
    """
    uid = uuid.uuid4().hex[:8]

    stmt = select(Role).where(Role.name == ROLE_ADMIN)
    role = (await db_session.execute(stmt)).scalar_one()

    user = User(
        id=f"usr_test_{uid}",
        tenant_id=test_tenant.id,
        role_id=role.id,
        email=f"testadmin_{uid}@jros-test.com",
        phone=None,
        hashed_password=hash_password("TestPass@123"),
        name=f"Test Admin {uid}",
        kyc_status="Verified",
        member_since="July 2026",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()

    from sqlalchemy.orm import selectinload
    stmt2 = select(User).options(selectinload(User.role)).where(User.id == user.id)
    user_loaded = (await db_session.execute(stmt2)).scalar_one()
    return user_loaded


@pytest.fixture(scope="function")
def admin_token(admin_user: User) -> Dict[str, str]:
    """Returns a valid JWT access + refresh token pair for the test admin."""
    token_id = f"tkn_test_{uuid.uuid4().hex[:12]}"
    access = create_access_token(
        subject=admin_user.id,
        tenant_id=admin_user.tenant_id,
        role=ROLE_ADMIN,
    )
    refresh = create_refresh_token(
        subject=admin_user.id,
        tenant_id=admin_user.tenant_id,
        token_id=token_id,
    )
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_id": token_id,
    }


@pytest.fixture(scope="function")
def admin_auth_headers(admin_token: Dict[str, str]) -> Dict[str, str]:
    """Authorization header dict for test admin."""
    return {"Authorization": f"Bearer {admin_token['access_token']}"}


# ─────────────────────────────────────────────
# SuperAdmin Token
# ─────────────────────────────────────────────

@pytest_asyncio.fixture(scope="function")
async def superadmin_user(db_session: AsyncSession) -> User:
    """
    Fetches the seeded SuperAdmin user from the live database.
    Does NOT create or delete — uses the pre-seeded account.
    """
    from sqlalchemy.orm import selectinload
    stmt = (
        select(User)
        .options(selectinload(User.role))
        .where(User.email == settings.SUPERADMIN_EMAIL)
    )
    user = (await db_session.execute(stmt)).scalar_one()
    return user


@pytest.fixture(scope="function")
def superadmin_token(superadmin_user: User) -> Dict[str, str]:
    """JWT tokens for the seeded SuperAdmin account."""
    token_id = f"tkn_sa_{uuid.uuid4().hex[:12]}"
    access = create_access_token(
        subject=superadmin_user.id,
        tenant_id=None,
        role=ROLE_SUPERADMIN,
    )
    refresh = create_refresh_token(
        subject=superadmin_user.id,
        tenant_id=None,
        token_id=token_id,
    )
    return {"access_token": access, "refresh_token": refresh}


@pytest.fixture(scope="function")
def superadmin_auth_headers(superadmin_token: Dict[str, str]) -> Dict[str, str]:
    """Authorization header dict for SuperAdmin."""
    return {"Authorization": f"Bearer {superadmin_token['access_token']}"}


# ─────────────────────────────────────────────
# Utility Helpers
# ─────────────────────────────────────────────

def make_auth_headers(token: str) -> Dict[str, str]:
    """Build Authorization header dict from a raw access token string."""
    return {"Authorization": f"Bearer {token}"}


def unique_email() -> str:
    """Generate a unique test email address."""
    return f"test_{uuid.uuid4().hex[:8]}@jros-test.com"


def unique_phone() -> str:
    """Generate a unique valid Indian 10-digit phone number."""
    # Starts with 9, followed by 9 digits derived from uuid
    suffix = str(int(uuid.uuid4().hex[:9], 16))[:9].zfill(9)
    return f"9{suffix}"
