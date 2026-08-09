"""
SuperAdmin Integrations — provider abstraction.

Credentials for every provider here live in environment variables (see
config.py / .env.example), never in the database — matching the existing
SMTP_HOST/SUPABASE_URL/GOLDAPI_KEY convention already used across the
codebase. `configured` is computed live from settings on every call, never
cached or stored, so it can never drift from reality. The `platform_integrations`
table (app/models/integration.py) only stores the SuperAdmin-controlled
enabled/disabled toggle plus the last connection-test result — never a
secret.

Adding a real provider later (e.g. wiring an actual WhatsApp Business API
call) means implementing that provider's `test()`/`send()` and setting its
env vars — the DB schema, endpoints, and frontend UI do not change.
"""
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from app.core.config import settings

CATEGORY_GOLD_RATE = "gold_rate"
CATEGORY_MESSAGING = "messaging"
CATEGORY_PAYMENTS = "payments"


@dataclass(frozen=True)
class ProviderDefinition:
    key: str
    label: str
    category: str
    is_configured: Callable[[], bool]


def _gold_rate_configured() -> bool:
    return bool(settings.METALPRICEAPI_KEY or settings.IBJA_API_KEY or settings.GOLDAPI_KEY)


def _email_configured() -> bool:
    return bool(settings.SMTP_HOST)


def _whatsapp_configured() -> bool:
    return bool(settings.WHATSAPP_API_KEY and settings.WHATSAPP_PHONE_NUMBER_ID)


def _sms_configured() -> bool:
    return bool(settings.SMS_API_KEY)


def _payment_gateway_configured() -> bool:
    return bool(settings.PAYMENT_GATEWAY_API_KEY and settings.PAYMENT_GATEWAY_SECRET)


PROVIDER_REGISTRY: Dict[str, ProviderDefinition] = {
    "gold_rate": ProviderDefinition("gold_rate", "Gold Rate Provider", CATEGORY_GOLD_RATE, _gold_rate_configured),
    "email": ProviderDefinition("email", "Email / SMTP", CATEGORY_MESSAGING, _email_configured),
    "whatsapp": ProviderDefinition("whatsapp", "WhatsApp", CATEGORY_MESSAGING, _whatsapp_configured),
    "sms": ProviderDefinition("sms", "SMS", CATEGORY_MESSAGING, _sms_configured),
    "payment_gateway": ProviderDefinition("payment_gateway", "Payment Gateway", CATEGORY_PAYMENTS, _payment_gateway_configured),
}


def get_provider(key: str) -> Optional[ProviderDefinition]:
    return PROVIDER_REGISTRY.get(key)


def list_providers() -> List[ProviderDefinition]:
    return list(PROVIDER_REGISTRY.values())


def is_channel_configured(channel: str) -> bool:
    """Notification-channel -> provider mapping. IN_APP has no external
    provider — it's always considered "configured" since it only ever
    writes to our own database."""
    if channel == "IN_APP":
        return True
    provider_key = {"EMAIL": "email", "WHATSAPP": "whatsapp", "SMS": "sms"}.get(channel)
    if not provider_key:
        # PUSH has no provider abstraction yet — always honestly "not configured".
        return False
    provider = get_provider(provider_key)
    return bool(provider and provider.is_configured())
