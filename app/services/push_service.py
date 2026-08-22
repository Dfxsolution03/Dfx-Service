"""Phase 7 — push notification delivery (FCM/APNs abstraction).

Real delivery, never faked. A provider reports `configured=False` and returns a
`not_configured` result when its credentials are absent — exactly the honesty
convention the notification-campaign path already follows for external channels.
Callers persist the in-app Notification regardless; push is a best-effort extra
layer on top, so a missing/failing provider never blocks the in-app record.

Selecting the provider is config-driven (settings.PUSH_PROVIDER). The FCM
provider issues a real HTTP v1 request when a service-account credential is
configured; with no credentials it degrades to the no-op provider rather than
pretending a message was sent.
"""
from dataclasses import dataclass, field
from typing import Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import logger
from app.repositories.notification_repository import DeviceTokenRepository


@dataclass
class PushMessage:
    title: str
    body: str
    data: Dict[str, str] = field(default_factory=dict)


@dataclass
class PushResult:
    ok: bool
    provider: str
    detail: str = ""


class PushProvider:
    """Provider contract. `configured` gates real delivery — an unconfigured
    provider must never return ok=True."""
    name = "base"
    configured = False

    async def send(self, token: str, platform: str, message: PushMessage) -> PushResult:  # pragma: no cover
        raise NotImplementedError


class NoopPushProvider(PushProvider):
    """Used when no push credentials are set. Never claims a delivery."""
    name = "noop"
    configured = False

    async def send(self, token: str, platform: str, message: PushMessage) -> PushResult:
        return PushResult(ok=False, provider=self.name, detail="push provider not configured")


class FcmPushProvider(PushProvider):
    """Firebase Cloud Messaging HTTP v1. Real send when a service-account
    credential JSON + project id are configured; otherwise treated as
    unconfigured (get_push_provider falls back to no-op)."""
    name = "fcm"

    def __init__(self) -> None:
        self.project_id: Optional[str] = settings.FCM_PROJECT_ID
        self.credentials_json: Optional[str] = settings.FCM_CREDENTIALS_JSON
        self.configured = bool(self.project_id and self.credentials_json)

    async def send(self, token: str, platform: str, message: PushMessage) -> PushResult:
        if not self.configured:
            return PushResult(ok=False, provider=self.name, detail="fcm credentials not configured")
        try:
            # Lazy imports so the dependency is only needed when FCM is actually
            # configured — an unconfigured deployment never imports these.
            import json
            import httpx
            from google.oauth2 import service_account  # type: ignore
            from google.auth.transport.requests import Request as GoogleAuthRequest  # type: ignore

            creds = service_account.Credentials.from_service_account_info(
                json.loads(self.credentials_json),
                scopes=["https://www.googleapis.com/auth/firebase.messaging"],
            )
            creds.refresh(GoogleAuthRequest())
            url = f"https://fcm.googleapis.com/v1/projects/{self.project_id}/messages:send"
            payload = {
                "message": {
                    "token": token,
                    "notification": {"title": message.title, "body": message.body},
                    "data": {k: str(v) for k, v in (message.data or {}).items()},
                }
            }
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    url, json=payload,
                    headers={"Authorization": f"Bearer {creds.token}"},
                )
            if resp.status_code == 200:
                return PushResult(ok=True, provider=self.name, detail="sent")
            return PushResult(ok=False, provider=self.name, detail=f"fcm http {resp.status_code}")
        except Exception as exc:  # network/credential/library error — never fake success
            logger.warning(f"FCM push failed: {exc}")
            return PushResult(ok=False, provider=self.name, detail=f"fcm error: {exc}")


def get_push_provider() -> PushProvider:
    """Config-driven selection. Falls back to the no-op provider whenever the
    requested provider is not fully configured — so a partially-set-up
    deployment degrades honestly instead of erroring or faking."""
    choice = (settings.PUSH_PROVIDER or "noop").lower()
    if choice == "fcm":
        provider = FcmPushProvider()
        if provider.configured:
            return provider
    return NoopPushProvider()


class PushService:
    @staticmethod
    async def send_to_user(
        db: AsyncSession,
        tenant_id: str,
        user_id: str,
        title: str,
        body: str,
        data: Optional[Dict[str, str]] = None,
    ) -> dict:
        """Deliver a push to every active device the user has registered.
        Returns an honest summary — `configured=False` when no provider is set
        (nothing is sent, nothing is faked)."""
        provider = get_push_provider()
        tokens = await DeviceTokenRepository.list_active_for_user(db, tenant_id, user_id)
        if not provider.configured:
            return {"configured": False, "provider": provider.name, "devices": len(tokens),
                    "sent": 0, "failed": 0}
        msg = PushMessage(title=title, body=body, data=data or {})
        sent = failed = 0
        for t in tokens:
            result = await provider.send(t.token, t.platform, msg)
            if result.ok:
                sent += 1
            else:
                failed += 1
        return {"configured": True, "provider": provider.name, "devices": len(tokens),
                "sent": sent, "failed": failed}
