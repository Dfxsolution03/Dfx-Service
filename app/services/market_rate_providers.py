"""
Market rate provider extension points — Module 31.

Mirrors this codebase's existing StorageProvider (storage_service.py) /
PaymentGatewayProvider (payment_gateway.py) ABC + factory convention:
switching providers becomes a config change (MARKET_RATE_PROVIDER), not a
code rewrite.

Phase 1: MetalPriceAPIProvider is a real implementation. IBJAProvider and
GoldAPIProvider remain stubs indefinitely until their respective commercial
terms are finalized, exactly like PaymentGatewayProvider's documented
pattern.
"""

import asyncio
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

import httpx

from app.core.config import settings
from app.core.logging import logger

# 1 troy ounce = 31.1034768 grams (exact, internationally standardized).
TROY_OUNCE_GRAMS = Decimal("31.1034768")

# Sanity bounds for a per-gram INR rate — guards against a provider glitch
# (e.g. a wrong-unit response) silently corrupting the historical record.
# Wide enough to tolerate real multi-year market movement without needing
# frequent adjustment.
_GOLD_SANITY_MIN = Decimal("1000")
_GOLD_SANITY_MAX = Decimal("50000")
_SILVER_SANITY_MIN = Decimal("10")
_SILVER_SANITY_MAX = Decimal("1000")


class MarketRateProviderError(Exception):
    """Raised by any provider on fetch/parse/validation failure. Deliberately
    a plain Exception (not JROSException) — this never crosses into an HTTP
    response; only MarketRateSyncService catches it."""


@dataclass
class MarketRateSnapshot:
    """What a successful fetch_rates() call returns. Deliberately plain (not
    a MarketRate model instance) — the provider layer must not know about
    persistence; MarketRateSyncService maps this onto a MarketRate row."""
    provider: str
    gold_24k: float
    silver_999: Optional[float]
    currency: str
    unit: str
    raw_payload: Optional[str] = None
    provider_metadata: Optional[str] = None


class MarketRateProvider(ABC):
    """Abstract interface every concrete provider adapter implements."""

    @abstractmethod
    async def fetch_rates(self) -> MarketRateSnapshot:
        raise NotImplementedError


class MetalPriceAPIProvider(MarketRateProvider):
    """
    Real implementation — https://metalpriceapi.com/documentation

    GET /v1/latest?api_key=...&base=INR&currencies=XAU,XAG returns rates as
    "1 unit of base per unit of metal" AND the inverse "{BASE}{METAL}" key,
    which is the metal's price in the base currency per troy ounce. Fetching
    with base=INR directly avoids a separate USD->INR forex conversion step.

    Never logs or raises an error containing the API key or the full
    request URL (which carries the key as a query parameter) — only status
    codes, durations, and metal values are logged.
    """

    _URL = "https://api.metalpriceapi.com/v1/latest"

    async def fetch_rates(self) -> MarketRateSnapshot:
        if not settings.METALPRICEAPI_KEY:
            raise MarketRateProviderError("METALPRICEAPI_KEY is not configured")

        last_error: Optional[Exception] = None
        total_attempts = settings.MARKET_RATE_RETRY_COUNT + 1
        for attempt in range(total_attempts):
            try:
                return await self._fetch_once()
            except MarketRateProviderError as exc:
                last_error = exc
                is_last_attempt = attempt == total_attempts - 1
                if not is_last_attempt:
                    delay = settings.MARKET_RATE_RETRY_DELAY_SECONDS * (2 ** attempt)
                    logger.warning(
                        f"[MetalPriceAPIProvider] attempt {attempt + 1}/{total_attempts} "
                        f"failed: {exc} — retrying in {delay}s"
                    )
                    await asyncio.sleep(delay)

        # All attempts exhausted.
        raise last_error  # type: ignore[misc]

    async def _fetch_once(self) -> MarketRateSnapshot:
        params = {
            "api_key": settings.METALPRICEAPI_KEY,
            "base": "INR",
            "currencies": "XAU,XAG",
        }
        try:
            async with httpx.AsyncClient(timeout=settings.MARKET_RATE_FETCH_TIMEOUT_SECONDS) as client:
                response = await client.get(self._URL, params=params)
        except httpx.TimeoutException as exc:
            raise MarketRateProviderError(f"MetalpriceAPI request timed out: {type(exc).__name__}") from exc
        except httpx.HTTPError as exc:
            # str(exc) on some httpx errors can include the request URL
            # (with the api_key query param) — never interpolate exc
            # directly into a message that gets logged.
            raise MarketRateProviderError(f"MetalpriceAPI request failed: {type(exc).__name__}") from exc

        if response.status_code != 200:
            raise MarketRateProviderError(
                f"MetalpriceAPI returned HTTP {response.status_code}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise MarketRateProviderError(f"MetalpriceAPI returned non-JSON response: {exc}") from exc

        if not isinstance(payload, dict) or not payload.get("success"):
            raise MarketRateProviderError(f"MetalpriceAPI reported failure: success={payload.get('success') if isinstance(payload, dict) else 'N/A'}")

        rates = payload.get("rates")
        if not isinstance(rates, dict):
            raise MarketRateProviderError("MetalpriceAPI response missing 'rates' object")

        gold_oz_inr = rates.get("INRXAU")
        silver_oz_inr = rates.get("INRXAG")

        if gold_oz_inr is None:
            raise MarketRateProviderError("MetalpriceAPI response missing INRXAU rate")

        try:
            gold_24k = Decimal(str(gold_oz_inr)) / TROY_OUNCE_GRAMS
            silver_999 = (
                Decimal(str(silver_oz_inr)) / TROY_OUNCE_GRAMS
                if silver_oz_inr is not None else None
            )
        except (ArithmeticError, ValueError) as exc:
            raise MarketRateProviderError(f"MetalpriceAPI returned non-numeric rate: {exc}") from exc

        if not (_GOLD_SANITY_MIN <= gold_24k <= _GOLD_SANITY_MAX):
            raise MarketRateProviderError(f"Gold rate {gold_24k} outside sane bounds — rejecting")
        if silver_999 is not None and not (_SILVER_SANITY_MIN <= silver_999 <= _SILVER_SANITY_MAX):
            raise MarketRateProviderError(f"Silver rate {silver_999} outside sane bounds — rejecting")

        metadata = {
            "source_timestamp": payload.get("timestamp"),
            "unit_conversion": "troy_ounce_to_gram",
            "troy_ounce_grams": str(TROY_OUNCE_GRAMS),
        }

        return MarketRateSnapshot(
            provider="METALPRICEAPI",
            gold_24k=float(gold_24k),
            silver_999=float(silver_999) if silver_999 is not None else None,
            currency="INR",
            unit="PER_GRAM",
            raw_payload=json.dumps(payload),
            provider_metadata=json.dumps(metadata),
        )


class IBJAProvider(MarketRateProvider):
    """Stub — pending IBJA commercial terms (see Module 31 architecture
    doc). Not implemented yet."""

    async def fetch_rates(self) -> MarketRateSnapshot:
        raise NotImplementedError(
            "IBJAProvider is not implemented yet — pending commercial terms."
        )


class GoldAPIProvider(MarketRateProvider):
    """Stub — future alternative provider. Not implemented yet."""

    async def fetch_rates(self) -> MarketRateSnapshot:
        raise NotImplementedError(
            "GoldAPIProvider is not implemented yet."
        )


_PROVIDERS = {
    "METALPRICEAPI": MetalPriceAPIProvider,
    "IBJA": IBJAProvider,
    "GOLDAPI": GoldAPIProvider,
}


def get_market_rate_provider() -> MarketRateProvider:
    """Factory — selects a provider class by settings.MARKET_RATE_PROVIDER.
    Raises ValueError for an unrecognized name."""
    provider_name = settings.MARKET_RATE_PROVIDER.upper()
    provider_cls = _PROVIDERS.get(provider_name)
    if provider_cls is None:
        raise ValueError(
            f"Unknown MARKET_RATE_PROVIDER '{provider_name}'. "
            f"Valid options: {', '.join(_PROVIDERS.keys())}"
        )
    return provider_cls()
