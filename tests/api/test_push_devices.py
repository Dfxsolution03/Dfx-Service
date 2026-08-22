"""
DFX Backend Tests — Phase 7: push device registration + provider abstraction
=============================================================================

Schema + provider tests need no database. The service/DB tests use the shared
async fixtures and require Postgres (TEST_DATABASE_URL). Heavy imports are inside
the test methods.
"""
import uuid

import pytest

from app.schemas.notification import DeviceRegisterRequest, DeviceUnregisterRequest


# ───────────────────────── Pure schema tests (no database) ─────────────────────────

class TestDeviceSchemas:
    def test_valid_registration(self):
        r = DeviceRegisterRequest(token="abcd1234efgh", platform="ANDROID")
        assert r.provider == "FCM"

    def test_bad_platform_rejected(self):
        with pytest.raises(Exception):
            DeviceRegisterRequest(token="abcd1234efgh", platform="SYMBIAN")

    def test_short_token_rejected(self):
        with pytest.raises(Exception):
            DeviceRegisterRequest(token="x", platform="IOS")

    def test_unregister_request(self):
        assert DeviceUnregisterRequest(token="abcd1234efgh").token == "abcd1234efgh"


# ───────────────── Provider abstraction (no DB, but needs app importable) ─────────────────

class TestPushProvider:
    def test_noop_never_fakes_delivery(self):
        import asyncio
        from app.services.push_service import NoopPushProvider, PushMessage
        p = NoopPushProvider()
        assert p.configured is False
        res = asyncio.get_event_loop().run_until_complete(
            p.send("tok", "ANDROID", PushMessage(title="t", body="b"))
        )
        assert res.ok is False
        assert "not configured" in res.detail

    def test_default_provider_is_noop_when_unconfigured(self):
        from app.services.push_service import get_push_provider, NoopPushProvider
        # Default settings have PUSH_PROVIDER="noop" and no FCM creds.
        assert isinstance(get_push_provider(), NoopPushProvider)


# ───────────────── DB-backed integration tests (require Postgres) ─────────────────

class TestDeviceRegistration:
    async def test_register_is_idempotent(self, db_session, customer_user):
        from app.services.notification_service import NotificationService
        from app.repositories.notification_repository import DeviceTokenRepository
        token = f"tok-{uuid.uuid4().hex}"
        await NotificationService.register_device(
            db_session, customer_user, DeviceRegisterRequest(token=token, platform="ANDROID")
        )
        # Re-register the same token → same single row, reactivated.
        await NotificationService.register_device(
            db_session, customer_user, DeviceRegisterRequest(token=token, platform="IOS", provider="APNS")
        )
        rows = await DeviceTokenRepository.list_active_for_user(
            db_session, customer_user.tenant_id, customer_user.id
        )
        matching = [r for r in rows if r.token == token]
        assert len(matching) == 1
        assert matching[0].platform == "IOS"

    async def test_unregister_deactivates(self, db_session, customer_user):
        from app.services.notification_service import NotificationService
        from app.repositories.notification_repository import DeviceTokenRepository
        token = f"tok-{uuid.uuid4().hex}"
        await NotificationService.register_device(
            db_session, customer_user, DeviceRegisterRequest(token=token, platform="WEB")
        )
        await NotificationService.unregister_device(db_session, customer_user, token)
        rows = await DeviceTokenRepository.list_active_for_user(
            db_session, customer_user.tenant_id, customer_user.id
        )
        assert all(r.token != token for r in rows)

    async def test_unregister_foreign_token_not_found(self, db_session, customer_user):
        from app.services.notification_service import NotificationService
        from app.exceptions.base import ResourceNotFoundException
        with pytest.raises(ResourceNotFoundException):
            await NotificationService.unregister_device(db_session, customer_user, "no-such-token-xyz")

    async def test_send_to_user_unconfigured_reports_honestly(self, db_session, customer_user):
        from app.services.notification_service import NotificationService
        from app.services.push_service import PushService
        token = f"tok-{uuid.uuid4().hex}"
        await NotificationService.register_device(
            db_session, customer_user, DeviceRegisterRequest(token=token, platform="ANDROID")
        )
        result = await PushService.send_to_user(
            db_session, customer_user.tenant_id, customer_user.id, "Title", "Body"
        )
        # No provider configured in tests → nothing sent, nothing faked.
        assert result["configured"] is False
        assert result["sent"] == 0
        assert result["devices"] >= 1
