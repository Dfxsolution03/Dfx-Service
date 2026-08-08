"""
Module 31 / Phase 1 — MetalPriceAPIProvider tests. All external HTTP is
mocked via a scripted fake httpx.AsyncClient; the real provider is never
called during tests.
"""
import httpx
import pytest

from app.core.config import settings
from app.services import market_rate_providers as mrp
from app.services.market_rate_providers import (
    get_market_rate_provider,
    MetalPriceAPIProvider,
    IBJAProvider,
    GoldAPIProvider,
    MarketRateProviderError,
)


SUCCESS_PAYLOAD = {
    "success": True,
    "base": "INR",
    "timestamp": 1625609377,
    "rates": {"INRXAU": 305000.0, "INRXAG": 3670.0},
}


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}

    def json(self):
        return self._json_data


class _ScriptedAsyncClient:
    """Each .get() call pops the next scripted item — a response to return
    or an exception to raise. Set _ScriptedAsyncClient.script before use."""
    script = []
    calls = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, url, params=None):
        _ScriptedAsyncClient.calls.append((url, params))
        item = _ScriptedAsyncClient.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture(autouse=True)
def _fast_retry_delay(monkeypatch):
    # Keep tests fast — retry-with-backoff tests don't need real seconds.
    monkeypatch.setattr(settings, "MARKET_RATE_RETRY_DELAY_SECONDS", 0)
    monkeypatch.setattr(settings, "MARKET_RATE_RETRY_COUNT", 2)
    monkeypatch.setattr(settings, "METALPRICEAPI_KEY", "test-key")


@pytest.fixture
def scripted_client(monkeypatch):
    _ScriptedAsyncClient.script = []
    _ScriptedAsyncClient.calls = []
    monkeypatch.setattr(mrp.httpx, "AsyncClient", _ScriptedAsyncClient)
    return _ScriptedAsyncClient


# --- Provider factory ------------------------------------------------------

def test_factory_returns_configured_provider(monkeypatch):
    monkeypatch.setattr(settings, "MARKET_RATE_PROVIDER", "METALPRICEAPI")
    assert isinstance(get_market_rate_provider(), MetalPriceAPIProvider)
    monkeypatch.setattr(settings, "MARKET_RATE_PROVIDER", "IBJA")
    assert isinstance(get_market_rate_provider(), IBJAProvider)
    monkeypatch.setattr(settings, "MARKET_RATE_PROVIDER", "GOLDAPI")
    assert isinstance(get_market_rate_provider(), GoldAPIProvider)


def test_factory_raises_for_unknown_provider(monkeypatch):
    monkeypatch.setattr(settings, "MARKET_RATE_PROVIDER", "NOT_REAL")
    with pytest.raises(ValueError):
        get_market_rate_provider()


async def test_ibja_and_goldapi_still_stubs():
    with pytest.raises(NotImplementedError):
        await IBJAProvider().fetch_rates()
    with pytest.raises(NotImplementedError):
        await GoldAPIProvider().fetch_rates()


# --- Successful fetch --------------------------------------------------

async def test_successful_fetch_parses_and_converts_units(scripted_client):
    scripted_client.script = [_FakeResponse(200, SUCCESS_PAYLOAD)]
    snapshot = await MetalPriceAPIProvider().fetch_rates()

    assert snapshot.provider == "METALPRICEAPI"
    assert snapshot.currency == "INR"
    assert snapshot.unit == "PER_GRAM"
    # 305,000 INR per troy oz / 31.1034768 g per oz ≈ 9806 INR/g
    assert 9700 < snapshot.gold_24k < 9900
    assert 110 < snapshot.silver_999 < 125
    assert snapshot.raw_payload is not None
    assert "INRXAU" in snapshot.raw_payload
    assert snapshot.provider_metadata is not None


async def test_api_key_never_appears_in_raised_errors(scripted_client, monkeypatch):
    monkeypatch.setattr(settings, "METALPRICEAPI_KEY", "super-secret-key-12345")
    scripted_client.script = [httpx.TimeoutException("boom")] * 3
    with pytest.raises(MarketRateProviderError) as exc_info:
        await MetalPriceAPIProvider().fetch_rates()
    assert "super-secret-key-12345" not in str(exc_info.value)


# --- Invalid provider response ------------------------------------------

async def test_invalid_response_missing_success_flag(scripted_client):
    # Provider errors are retried (settings.MARKET_RATE_RETRY_COUNT=2 here,
    # via the module's autouse fixture) — a deterministic bad response must
    # be scripted for every attempt, not just the first.
    scripted_client.script = [_FakeResponse(200, {"rates": {"INRXAU": 305000.0}})] * 3
    with pytest.raises(MarketRateProviderError, match="reported failure"):
        await MetalPriceAPIProvider().fetch_rates()


async def test_invalid_response_missing_gold_rate(scripted_client):
    scripted_client.script = [_FakeResponse(200, {"success": True, "rates": {"INRXAG": 3670.0}})] * 3
    with pytest.raises(MarketRateProviderError, match="INRXAU"):
        await MetalPriceAPIProvider().fetch_rates()


async def test_invalid_response_out_of_bounds_rate(scripted_client):
    # 1 INR/oz -> ~0.03 INR/gram, absurd — must be rejected, not persisted.
    bad_payload = {"success": True, "rates": {"INRXAU": 1.0, "INRXAG": 3670.0}}
    scripted_client.script = [_FakeResponse(200, bad_payload)] * 3
    with pytest.raises(MarketRateProviderError, match="sane bounds"):
        await MetalPriceAPIProvider().fetch_rates()


async def test_non_200_status(scripted_client):
    scripted_client.script = [_FakeResponse(500, {})] * 3
    with pytest.raises(MarketRateProviderError, match="HTTP 500"):
        await MetalPriceAPIProvider().fetch_rates()


async def test_missing_api_key_raises_without_calling_http(monkeypatch, scripted_client):
    monkeypatch.setattr(settings, "METALPRICEAPI_KEY", "")
    with pytest.raises(MarketRateProviderError, match="not configured"):
        await MetalPriceAPIProvider().fetch_rates()
    assert scripted_client.calls == []  # never attempted a request


# --- Timeout -------------------------------------------------------------

async def test_timeout_raises_provider_error(scripted_client):
    scripted_client.script = [httpx.TimeoutException("timed out")] * 3
    with pytest.raises(MarketRateProviderError, match="timed out"):
        await MetalPriceAPIProvider().fetch_rates()


# --- Retry behavior --------------------------------------------------------

async def test_retries_then_succeeds(scripted_client):
    scripted_client.script = [
        httpx.TimeoutException("timeout 1"),
        httpx.TimeoutException("timeout 2"),
        _FakeResponse(200, SUCCESS_PAYLOAD),
    ]
    snapshot = await MetalPriceAPIProvider().fetch_rates()
    assert snapshot.gold_24k > 0
    assert len(scripted_client.calls) == 3


async def test_exhausts_all_retries_then_raises(scripted_client, monkeypatch):
    monkeypatch.setattr(settings, "MARKET_RATE_RETRY_COUNT", 1)
    scripted_client.script = [httpx.TimeoutException("t1"), httpx.TimeoutException("t2")]
    with pytest.raises(MarketRateProviderError):
        await MetalPriceAPIProvider().fetch_rates()
    assert len(scripted_client.calls) == 2  # 1 initial + 1 retry, then gives up
