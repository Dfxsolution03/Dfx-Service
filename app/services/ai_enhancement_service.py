"""
AI enhancement extension point — Module 20 (AI Catalogue Studio Foundation).

NOTHING in this file calls an external AI API, requires a provider key, or
performs any image processing. It exists purely so that a real provider
(Remove.bg, Replicate, an in-house model, etc.) can be plugged in later
without redesigning the Product/ProductImage models, CatalogueService, or
the /catalogue/.../enhance route. Same pure-stub philosophy as
app/services/payment_gateway.py — unlike storage_service.py, there is no
safe automatic "console" fallback for image AI, so this does not attempt
one.

Do not implement AIEnhancementProvider as part of Module 20. Provider
selection, cost/quota handling, and async job queuing for slow operations
(e.g. HD upscale) are explicitly out of scope until the client picks a
provider.
"""

from abc import ABC, abstractmethod

from app.schemas.catalogue import AIEnhancementType

# Maps each button Module 20 asks for to the variant_type its (future) output
# would be stored as. AUTO_CROP and the rest that don't have a dedicated
# ProductImage variant slot fall back to ENHANCED — this mapping is what a
# future concrete provider's caller would consult, not business logic itself.
ENHANCEMENT_OUTPUT_VARIANT = {
    "REMOVE_BACKGROUND": "BACKGROUND_REMOVED",
    "HD_UPSCALE": "ENHANCED",
    # Module 21 added a dedicated LUXURY_LIGHTING variant (it's its own named
    # stop on the processing pipeline, distinct from the generic ENHANCED
    # bucket) — updated to point at it instead of falling into ENHANCED.
    "LUXURY_LIGHTING": "LUXURY_LIGHTING",
    "DIAMOND_ENHANCEMENT": "ENHANCED",
    "GOLD_SHINE": "ENHANCED",
    "REFLECTION_REMOVAL": "ENHANCED",
    "AUTO_CROP": "ENHANCED",
    "SHADOW_CORRECTION": "ENHANCED",
}


class AIEnhancementProvider(ABC):
    """
    Abstract interface a future concrete provider adapter would implement.
    No subclass exists yet.
    """

    @abstractmethod
    async def enhance(self, *, image_bytes: bytes, enhancement_type: AIEnhancementType) -> bytes:
        """Would call out to an external (or in-house) AI service and return
        the processed image bytes. Not implemented — raises on call."""
        raise NotImplementedError(
            "No AI enhancement provider is configured yet. This is an extension point for a future module."
        )


def get_ai_enhancement_provider() -> AIEnhancementProvider:
    """
    No provider exists yet — this always raises. CatalogueService calls this
    (not a concrete class directly) so that wiring in a real provider later
    is a one-line change here, not a change anywhere that calls it.
    """
    raise NotImplementedError(
        "AI enhancement is not yet configured for this platform. "
        "This is the plug-in point for a future provider."
    )


# =============================================================================
# Module 21 — AI Product Studio: reusable multi-vendor provider architecture.
#
# AIEnhancementProvider above (Module 20) is untouched and still the actual
# interface CatalogueService.enhance_image() calls through — this section
# only ADDS a broader shape (AIProvider) with one stub subclass per named
# vendor, exactly as Module 21 asked for. get_ai_provider() is wired into
# CatalogueService as the concrete implementation get_ai_enhancement_provider
# would delegate to once a real vendor is chosen — today it always resolves
# to StubProvider, so behavior is identical to Module 20's: a clean "not
# configured" error, nothing more.
#
# Do not implement OpenAIProvider/GoogleProvider/CloudinaryProvider/
# ReplicateProvider/FalProvider as part of Module 21 — same explicit
# instruction as Module 20 gave payment_gateway.py. Choosing a vendor,
# handling API keys/quotas/costs, and async job queuing for slow operations
# are all still out of scope until the client decides.
# =============================================================================


class AIProvider(ABC):
    """
    Generic vendor-agnostic interface. One method covers every Module 21
    operation (background removal, every enhancement type, and — once a
    provider exists — template/marketing-asset generation), since from an
    integration standpoint OpenAI/Google/Replicate/Fal/Cloudinary are all
    "send an image and an operation name, get an image back" services. This
    avoids five near-identical parallel class hierarchies for what is really
    one integration point per vendor.
    """

    #: Human-readable vendor name shown in the "not configured" message and
    #: in the admin UI's provider-status banner.
    name: str = "Unconfigured"

    @abstractmethod
    async def process(self, *, image_bytes: bytes, operation: str) -> bytes:
        """Would send image_bytes to the vendor for the given operation
        (an AIEnhancementType, or a future template/marketing-asset key) and
        return the processed image. Not implemented — raises on call."""
        raise NotImplementedError


class StubProvider(AIProvider):
    """
    The only provider that actually exists today. Always raises a clean,
    honest error — never returns a copied/placeholder image pretending to be
    a real result. This is what get_ai_provider() returns until a real
    vendor is configured.
    """

    name = "Stub"

    async def process(self, *, image_bytes: bytes, operation: str) -> bytes:
        # Wording deliberately matches Module 20's get_ai_enhancement_provider()
        # ("not yet configured") — CatalogueService.enhance_image()'s existing
        # test (Module 20) asserts on that exact phrase, and Module 21 must
        # extend that behavior, not change it.
        raise NotImplementedError(
            f"AI provider is not yet configured for '{operation}'. "
            "This is the plug-in point for a future module."
        )


class OpenAIProvider(AIProvider):
    """Extension point for OpenAI (e.g. gpt-image-1 / DALL-E edit endpoints).
    Not implemented — no API key handling, no request shaping exists yet."""

    name = "OpenAI"

    async def process(self, *, image_bytes: bytes, operation: str) -> bytes:
        raise NotImplementedError("OpenAI provider is not configured yet.")


class GoogleProvider(AIProvider):
    """Extension point for Google (e.g. Vertex AI Imagen). Not implemented."""

    name = "Google"

    async def process(self, *, image_bytes: bytes, operation: str) -> bytes:
        raise NotImplementedError("Google provider is not configured yet.")


class CloudinaryProvider(AIProvider):
    """Extension point for Cloudinary's AI add-ons (background removal,
    generative fill/upscale). Not implemented."""

    name = "Cloudinary"

    async def process(self, *, image_bytes: bytes, operation: str) -> bytes:
        raise NotImplementedError("Cloudinary provider is not configured yet.")


class ReplicateProvider(AIProvider):
    """Extension point for Replicate-hosted models. Not implemented."""

    name = "Replicate"

    async def process(self, *, image_bytes: bytes, operation: str) -> bytes:
        raise NotImplementedError("Replicate provider is not configured yet.")


class FalProvider(AIProvider):
    """Extension point for fal.ai-hosted models. Not implemented."""

    name = "Fal"

    async def process(self, *, image_bytes: bytes, operation: str) -> bytes:
        raise NotImplementedError("Fal provider is not configured yet.")


def get_ai_provider() -> AIProvider:
    """
    Factory a future module would extend with real vendor selection (e.g.
    reading an AI_PROVIDER=openai setting and real API keys from config,
    exactly like get_storage_provider()'s SUPABASE_URL check). No vendor is
    configured anywhere in this codebase yet, so this always returns
    StubProvider — identical externally-observable behavior to Module 20's
    get_ai_enhancement_provider(), just expressed through the broader
    multi-vendor shape Module 21 asked for.
    """
    return StubProvider()


def is_ai_provider_configured() -> bool:
    """Lets the frontend show an honest provider-status banner instead of
    only discovering "not configured" after a click."""
    return not isinstance(get_ai_provider(), StubProvider)
