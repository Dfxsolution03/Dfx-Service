"""
DFX Solution Service Tests — AI Provider Architecture (Module 21)
==================================================================
Pure unit tests, no DB — these just verify the extension-point shape:
every named provider is a real, importable class that raises a clean
NotImplementedError, and the factory always resolves to StubProvider until
a real vendor is configured (which nothing in this codebase does).
"""

import pytest

from app.services.ai_enhancement_service import (
    AIProvider,
    StubProvider,
    OpenAIProvider,
    GoogleProvider,
    CloudinaryProvider,
    ReplicateProvider,
    FalProvider,
    get_ai_provider,
    is_ai_provider_configured,
)


class TestProviderFactory:
    def test_get_ai_provider_returns_stub_by_default(self):
        provider = get_ai_provider()
        assert isinstance(provider, StubProvider)

    def test_is_ai_provider_configured_is_false_by_default(self):
        assert is_ai_provider_configured() is False


class TestStubProvider:
    async def test_process_raises_not_yet_configured(self):
        provider = StubProvider()
        with pytest.raises(NotImplementedError) as exc_info:
            await provider.process(image_bytes=b"x", operation="REMOVE_BACKGROUND")
        assert "not yet configured" in str(exc_info.value).lower()
        assert "REMOVE_BACKGROUND" in str(exc_info.value)


class TestNamedVendorStubs:
    """Every named vendor from Module 21's brief exists as a real class,
    inherits AIProvider, and is honestly unimplemented — none of this is
    wired to a real vendor SDK or API key."""

    @pytest.mark.parametrize(
        "provider_cls,vendor_name",
        [
            (OpenAIProvider, "OpenAI"),
            (GoogleProvider, "Google"),
            (CloudinaryProvider, "Cloudinary"),
            (ReplicateProvider, "Replicate"),
            (FalProvider, "Fal"),
        ],
    )
    async def test_named_provider_is_a_real_ai_provider_subclass(self, provider_cls, vendor_name):
        provider = provider_cls()
        assert isinstance(provider, AIProvider)
        assert provider.name == vendor_name
        with pytest.raises(NotImplementedError) as exc_info:
            await provider.process(image_bytes=b"x", operation="HD_UPSCALE")
        assert "not configured yet" in str(exc_info.value).lower()
