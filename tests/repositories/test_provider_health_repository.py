"""Module 31 / Phase 0 — model creation + repository scaffolding tests."""
import uuid

from app.models.provider_health import ProviderHealth, STATUS_UNKNOWN
from app.repositories.provider_health_repository import ProviderHealthRepository


async def test_create_and_get_by_provider(db_session):
    provider_name = f"TEST_PROVIDER_{uuid.uuid4().hex[:8]}"
    health = ProviderHealth(
        id=f"phl_test_{uuid.uuid4().hex[:12]}",
        provider=provider_name,
    )
    await ProviderHealthRepository.create(db_session, health)
    await db_session.commit()

    try:
        fetched = await ProviderHealthRepository.get_by_provider(db_session, provider_name)
        assert fetched is not None
        assert fetched.status == STATUS_UNKNOWN
        assert fetched.consecutive_failures == 0

        all_rows = await ProviderHealthRepository.list_all(db_session)
        assert any(h.provider == provider_name for h in all_rows)
    finally:
        from sqlalchemy import delete
        await db_session.execute(delete(ProviderHealth).where(ProviderHealth.id == health.id))
        await db_session.commit()
