import base64
import io
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from fastapi import UploadFile
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import logger
from app.models.auth import User
from app.models.catalogue import Product, ProductImage, CatalogueDesign
from app.repositories.catalogue_repository import CatalogueRepository
from app.repositories.audit_repository import AuditRepository
from app.services.storage_service import get_storage_provider
from app.services import image_processing_service
from app.services import catalogue_render_service
from app.services.catalogue_asset_library import (
    TEMPLATE_PRESETS,
    TEMPLATE_LABELS,
    TEMPLATE_CATEGORIES,
    OUTPUT_PRESETS,
    OUTPUT_PRESET_TO_VARIANT,
    RENDER_QUALITY_LEVELS,
    DEFAULT_RENDER_QUALITY,
)
from app.services.ai_enhancement_service import (
    get_ai_provider,
    is_ai_provider_configured,
)
from app.exceptions.base import (
    ResourceNotFoundException,
    ForbiddenException,
    ValidationException,
)
from app.schemas.catalogue import (
    ProductCreateRequest,
    ProductUpdateRequest,
    ProductResponse,
    ProductImageResponse,
    ImageReorderRequest,
    EnhancementRequest,
    StorageStatusResponse,
    AIProviderStatusResponse,
    PIPELINE_STAGES,
    PipelineStageStatus,
    PipelineStatusResponse,
    ImageEditRequest,
    ImageEditPreviewResponse,
    CanvasDocument,
    CanvasLayer,
    CatalogueDesignSaveRequest,
    CatalogueDesignResponse,
    CatalogueDesignCloneRequest,
    RenderPreviewRequest,
    RenderPreviewResponse,
    ExportDesignRequest,
    BatchRenderRequest,
    CataloguePdfRequest,
    CataloguePdfResponse,
    TemplateSummary,
    OutputPresetSummary,
)

# Only image types Module 20's upload flow accepts. Kept narrow on purpose —
# this is a jewellery photo catalogue, not a general file store.
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}

# Module 21 — Phase 8 (Performance): real thumbnails, not just a smaller
# <img> tag pointing at the full-size original. Longest edge, aspect
# preserved.
THUMBNAIL_MAX_DIMENSION = 320
_PIL_FORMAT_BY_CONTENT_TYPE = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
}


def _split_tags(tags_text: Optional[str]) -> List[str]:
    if not tags_text:
        return []
    return [t.strip() for t in tags_text.split(",") if t.strip()]


def _join_tags(tags: Optional[List[str]]) -> Optional[str]:
    if tags is None:
        return None
    cleaned = [t.strip() for t in tags if t.strip()]
    return ", ".join(cleaned) if cleaned else None


class CatalogueService:
    # -- Products -----------------------------------------------------------
    @staticmethod
    def _build_image_response(img: ProductImage, provider=None) -> ProductImageResponse:
        provider = provider or get_storage_provider()
        return ProductImageResponse(
            id=img.id,
            product_id=img.product_id,
            variant_type=img.variant_type,
            source_image_id=img.source_image_id,
            shot_type=img.shot_type,
            url=provider.get_public_url(img.storage_path),
            file_name=img.file_name,
            content_type=img.content_type,
            file_size_bytes=img.file_size_bytes,
            display_order=img.display_order,
            is_primary=img.is_primary,
            created_at=img.created_at,
        )

    @staticmethod
    def _build_product_response(product: Product) -> ProductResponse:
        provider = get_storage_provider()
        images = [
            CatalogueService._build_image_response(img, provider)
            for img in sorted(product.images, key=lambda i: (i.variant_type, i.display_order))
        ]
        primary = next((i for i in images if i.is_primary and i.variant_type == "ORIGINAL"), None)
        if not primary:
            primary = next((i for i in images if i.variant_type == "ORIGINAL"), None)
        return ProductResponse(
            id=product.id,
            tenant_id=product.tenant_id,
            name=product.name,
            description=product.description,
            category=product.category,
            sku=product.sku,
            purity=product.purity,
            price=product.price,
            weight_grams=product.weight_grams,
            tags=_split_tags(product.tags),
            is_active=product.is_active,
            created_by=product.created_by,
            created_at=product.created_at,
            updated_at=product.updated_at,
            images=images,
            primary_image_url=primary.url if primary else None,
            image_count=len(images),
        )

    @staticmethod
    def _generate_thumbnail_bytes(file_bytes: bytes, content_type: str) -> Optional[bytes]:
        """Module 21 — Phase 8. Best-effort: a thumbnail failure must never
        block the actual upload (the original is what matters), so this
        returns None on any error rather than raising."""
        pil_format = _PIL_FORMAT_BY_CONTENT_TYPE.get(content_type)
        if not pil_format:
            return None
        try:
            with Image.open(io.BytesIO(file_bytes)) as img:
                img = img.convert("RGB") if pil_format == "JPEG" else img
                img.thumbnail((THUMBNAIL_MAX_DIMENSION, THUMBNAIL_MAX_DIMENSION))
                buffer = io.BytesIO()
                img.save(buffer, format=pil_format)
                return buffer.getvalue()
        except Exception as e:
            logger.warning(f"Thumbnail generation failed, continuing without one: {e}")
            return None

    @staticmethod
    async def get_products(db: AsyncSession, current_user: User) -> List[ProductResponse]:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        products = await CatalogueRepository.get_products_by_tenant(db, current_user.tenant_id)
        return [CatalogueService._build_product_response(p) for p in products]

    @staticmethod
    async def get_product_by_id(
        db: AsyncSession, current_user: User, product_id: str
    ) -> ProductResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        product = await CatalogueRepository.get_product_by_id(db, product_id, current_user.tenant_id)
        if not product:
            raise ResourceNotFoundException(f"Product ID '{product_id}' not found")
        return CatalogueService._build_product_response(product)

    @staticmethod
    async def create_product(
        db: AsyncSession, current_user: User, req: ProductCreateRequest
    ) -> ProductResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        product_id = f"prd_{uuid.uuid4().hex[:12]}"
        product = Product(
            id=product_id,
            tenant_id=current_user.tenant_id,
            name=req.name,
            description=req.description,
            category=req.category,
            sku=req.sku,
            purity=req.purity,
            price=req.price,
            weight_grams=req.weight_grams,
            tags=_join_tags(req.tags),
            is_active=True,
            created_by=current_user.id,
        )
        await CatalogueRepository.create_product(db, product)

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="PRODUCT_CREATE",
            target_entity="products",
            target_id=product_id,
            before_state=None,
            after_state={"name": req.name, "category": req.category},
        )

        await db.commit()
        # Re-fetch through the repository rather than db.refresh(): refresh()
        # given an explicit attribute_names list only reloads exactly those
        # names, leaving any other already-expired attribute (e.g.
        # updated_at, which SQLAlchemy expires after a commit because its
        # onupdate=func.now() value is computed server-side) still expired —
        # accessing it later triggers an un-awaited lazy-load and crashes
        # with MissingGreenlet. A full re-fetch has no such gaps.
        product = await CatalogueRepository.get_product_by_id(db, product_id, current_user.tenant_id)
        return CatalogueService._build_product_response(product)

    @staticmethod
    async def update_product(
        db: AsyncSession, current_user: User, product_id: str, req: ProductUpdateRequest
    ) -> ProductResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        product = await CatalogueRepository.get_product_by_id(db, product_id, current_user.tenant_id)
        if not product:
            raise ResourceNotFoundException(f"Product ID '{product_id}' not found")

        before_state = {"name": product.name, "is_active": product.is_active}
        for field in ["name", "description", "category", "sku", "purity", "price", "weight_grams", "is_active"]:
            val = getattr(req, field, None)
            if val is not None:
                setattr(product, field, val)
        if req.tags is not None:
            product.tags = _join_tags(req.tags)

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="PRODUCT_UPDATE",
            target_entity="products",
            target_id=product_id,
            before_state=before_state,
            after_state={"name": product.name, "is_active": product.is_active},
        )

        await db.commit()
        # Re-fetch through the repository — see create_product's comment for
        # why db.refresh(attribute_names=[...]) isn't safe here: updated_at
        # gets expired by the commit (onupdate=func.now() is server-computed)
        # and a partial-attribute refresh doesn't reload it.
        product = await CatalogueRepository.get_product_by_id(db, product_id, current_user.tenant_id)
        return CatalogueService._build_product_response(product)

    @staticmethod
    async def deactivate_product(db: AsyncSession, current_user: User, product_id: str) -> None:
        """Soft-delete, same is_active convention as Scheme/Branch. Images
        and their stored files are left untouched — deactivating a product
        is not the same as deleting its media."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        product = await CatalogueRepository.get_product_by_id(db, product_id, current_user.tenant_id)
        if not product:
            raise ResourceNotFoundException(f"Product ID '{product_id}' not found")

        product.is_active = False

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="PRODUCT_DEACTIVATE",
            target_entity="products",
            target_id=product_id,
            before_state={"is_active": True},
            after_state={"is_active": False},
        )

        await db.commit()

    # -- Images ---------------------------------------------------------------
    @staticmethod
    async def upload_image(
        db: AsyncSession,
        current_user: User,
        product_id: str,
        file: UploadFile,
        shot_type: Optional[str] = None,
    ) -> ProductImageResponse:
        """Always creates a new ORIGINAL row — never overwrites an existing
        image, per Module 20's explicit requirement. Multiple uploads for the
        same product simply accumulate as separate gallery entries."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        product = await CatalogueRepository.get_product_by_id(db, product_id, current_user.tenant_id)
        if not product:
            raise ResourceNotFoundException(f"Product ID '{product_id}' not found")

        content_type = file.content_type or ""
        if content_type not in ALLOWED_CONTENT_TYPES:
            raise ValidationException(
                f"Unsupported image type '{content_type}'. Allowed: JPEG, PNG, WebP."
            )

        file_bytes = await file.read()
        if len(file_bytes) > settings.MAX_UPLOAD_SIZE_BYTES:
            max_mb = settings.MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)
            raise ValidationException(f"Image exceeds the {max_mb}MB upload limit.")
        if not file_bytes:
            raise ValidationException("Uploaded file is empty.")

        provider = get_storage_provider()
        storage_path = await provider.upload(
            tenant_id=current_user.tenant_id,
            file_name=file.filename or "upload",
            content_type=content_type,
            file_bytes=file_bytes,
        )

        # Performance: `product.images` was already eager-loaded by the
        # get_product_by_id call above (selectinload) — reuse it instead of
        # re-querying the exact same rows via a second, redundant query.
        originals = [i for i in product.images if i.variant_type == "ORIGINAL"]
        next_order = (max((i.display_order for i in originals), default=-1)) + 1
        is_first_image = len(originals) == 0

        image = ProductImage(
            id=f"img_{uuid.uuid4().hex[:12]}",
            product_id=product_id,
            tenant_id=current_user.tenant_id,
            variant_type="ORIGINAL",
            source_image_id=None,
            storage_path=storage_path,
            file_name=file.filename or "upload",
            content_type=content_type,
            file_size_bytes=len(file_bytes),
            display_order=next_order,
            # The very first original a product gets becomes primary
            # automatically — every subsequent upload requires an explicit
            # "set as primary" action, matching the established
            # "auto-promote only when nothing else can be primary" pattern
            # this codebase already uses for default addresses.
            is_primary=is_first_image,
            shot_type=shot_type,
            created_by=current_user.id,
        )
        await CatalogueRepository.create_image(db, image)

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="PRODUCT_IMAGE_UPLOAD",
            target_entity="product_images",
            target_id=image.id,
            before_state=None,
            after_state={"product_id": product_id, "variant_type": "ORIGINAL"},
        )

        await db.commit()
        await db.refresh(image)

        # Module 21 — Phase 8: a real thumbnail, generated once at upload
        # time rather than the frontend fetching (and the network paying
        # for) the full-size original everywhere a small preview is shown.
        # Best-effort — see _generate_thumbnail_bytes's own docstring.
        thumb_bytes = CatalogueService._generate_thumbnail_bytes(file_bytes, content_type)
        if thumb_bytes:
            try:
                thumb_storage_path = await provider.upload(
                    tenant_id=current_user.tenant_id,
                    file_name=f"thumb_{file.filename or 'upload'}",
                    content_type=content_type,
                    file_bytes=thumb_bytes,
                )
                thumbnail = ProductImage(
                    id=f"img_{uuid.uuid4().hex[:12]}",
                    product_id=product_id,
                    tenant_id=current_user.tenant_id,
                    variant_type="THUMBNAIL",
                    source_image_id=image.id,
                    storage_path=thumb_storage_path,
                    file_name=f"thumb_{image.file_name}",
                    content_type=content_type,
                    file_size_bytes=len(thumb_bytes),
                    display_order=0,
                    is_primary=False,
                    created_by=current_user.id,
                )
                await CatalogueRepository.create_image(db, thumbnail)
                await db.commit()
            except Exception as e:
                # Same reasoning as _generate_thumbnail_bytes: never let a
                # thumbnail problem fail the actual upload the user asked for.
                logger.warning(f"Thumbnail storage failed, continuing without one: {e}")
                await db.rollback()

        return CatalogueService._build_image_response(image, provider)

    @staticmethod
    async def set_primary_image(
        db: AsyncSession, current_user: User, product_id: str, image_id: str
    ) -> None:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        image = await CatalogueRepository.get_image_by_id(db, image_id, current_user.tenant_id)
        if not image or image.product_id != product_id:
            raise ResourceNotFoundException(f"Image ID '{image_id}' not found")
        if image.variant_type != "ORIGINAL":
            raise ValidationException("Only an original image can be set as primary.")

        await CatalogueRepository.clear_primary_flag(db, product_id, current_user.tenant_id)
        image.is_primary = True

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="PRODUCT_IMAGE_SET_PRIMARY",
            target_entity="product_images",
            target_id=image_id,
            before_state=None,
            after_state={"is_primary": True},
        )

        await db.commit()

    @staticmethod
    async def reorder_images(
        db: AsyncSession, current_user: User, product_id: str, req: ImageReorderRequest
    ) -> None:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        images = await CatalogueRepository.get_images_by_product(
            db, product_id, current_user.tenant_id
        )
        by_id = {img.id: img for img in images if img.variant_type == "ORIGINAL"}
        if set(req.image_ids) != set(by_id.keys()):
            raise ValidationException(
                "image_ids must contain exactly this product's current original images."
            )

        for index, image_id in enumerate(req.image_ids):
            by_id[image_id].display_order = index

        await db.commit()

    @staticmethod
    async def delete_image(
        db: AsyncSession, current_user: User, product_id: str, image_id: str
    ) -> None:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        image = await CatalogueRepository.get_image_by_id(db, image_id, current_user.tenant_id)
        if not image or image.product_id != product_id:
            raise ResourceNotFoundException(f"Image ID '{image_id}' not found")

        provider = get_storage_provider()
        was_primary = image.is_primary
        storage_path = image.storage_path

        await CatalogueRepository.delete_image(db, image)

        # If the deleted image was primary, auto-promote the next remaining
        # original — same "never leave zero primaries when one is
        # available" rule already established for default addresses.
        if was_primary:
            remaining = await CatalogueRepository.get_images_by_product(
                db, product_id, current_user.tenant_id
            )
            remaining_originals = sorted(
                (i for i in remaining if i.variant_type == "ORIGINAL" and i.id != image_id),
                key=lambda i: i.display_order,
            )
            if remaining_originals:
                remaining_originals[0].is_primary = True

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="PRODUCT_IMAGE_DELETE",
            target_entity="product_images",
            target_id=image_id,
            before_state={"variant_type": image.variant_type},
            after_state=None,
        )

        await db.commit()
        await provider.delete(storage_path)

    @staticmethod
    async def get_media_library(
        db: AsyncSession, current_user: User
    ) -> List[ProductImageResponse]:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        provider = get_storage_provider()
        images = await CatalogueRepository.get_all_images_by_tenant(db, current_user.tenant_id)
        return [CatalogueService._build_image_response(img, provider) for img in images]

    @staticmethod
    def get_storage_status() -> StorageStatusResponse:
        configured = bool(settings.SUPABASE_URL and settings.SUPABASE_SERVICE_ROLE_KEY)
        return StorageStatusResponse(
            provider="supabase" if configured else "local_disk",
            configured=True,  # local disk is always "configured" (it always works)
        )

    @staticmethod
    def get_ai_provider_status() -> AIProviderStatusResponse:
        """Module 21 — same purpose as get_storage_status(): lets the UI
        show a dynamic, honest banner instead of an assumed static one."""
        provider = get_ai_provider()
        return AIProviderStatusResponse(
            provider=provider.name,
            configured=is_ai_provider_configured(),
        )

    # -- AI Enhancement (extension point — see ai_enhancement_service.py) ----
    @staticmethod
    async def enhance_image(
        db: AsyncSession,
        current_user: User,
        product_id: str,
        image_id: str,
        req: EnhancementRequest,
    ) -> None:
        """Real, stable endpoint shape a future module wires a provider into.
        Today this always raises an honest, clean error — no fake success,
        no silently-copied 'enhanced' image standing in for a real one."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        image = await CatalogueRepository.get_image_by_id(db, image_id, current_user.tenant_id)
        if not image or image.product_id != product_id:
            raise ResourceNotFoundException(f"Image ID '{image_id}' not found")

        # Module 21: routes through the multi-vendor AIProvider architecture
        # (see ai_enhancement_service.py) instead of Module 20's narrower
        # get_ai_enhancement_provider() — same externally-observable "not
        # yet configured" behavior, since only StubProvider exists today.
        image_bytes = await CatalogueService._read_image_bytes(image)
        try:
            await get_ai_provider().process(
                image_bytes=image_bytes, operation=req.enhancement_type
            )
        except NotImplementedError as e:
            raise ValidationException(str(e))

    @staticmethod
    async def _read_image_bytes(image: ProductImage) -> bytes:
        provider = get_storage_provider()
        return await provider.download(image.storage_path)

    @staticmethod
    async def _get_owned_image(
        db: AsyncSession, current_user: User, product_id: str, image_id: str
    ) -> ProductImage:
        """Shared lookup + tenant/product ownership check for the Image
        Editor's preview/save pair — same 404-not-403 convention as every
        other per-image method in this service."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        image = await CatalogueRepository.get_image_by_id(db, image_id, current_user.tenant_id)
        if not image or image.product_id != product_id:
            raise ResourceNotFoundException(f"Image ID '{image_id}' not found")
        return image

    # -- Image Editor (Jewellery Catalogue & Marketing Studio, Phase A) ------
    # Real, local Pillow/OpenCV processing — a completely separate concern
    # from the AI-provider extension point above. Session model: Original
    # Image -> Editing Session (client-held operations list, ephemeral) ->
    # Preview (rendered on demand, never persisted) -> Save (persisted
    # exactly once, as a new EDITED ProductImage row). Every intermediate
    # adjustment while editing — and every Preview call — leaves no trace in
    # the DB; only save_edit_image() writes anything.
    @staticmethod
    async def preview_edit_image(
        db: AsyncSession,
        current_user: User,
        product_id: str,
        image_id: str,
        req: ImageEditRequest,
    ) -> ImageEditPreviewResponse:
        image = await CatalogueService._get_owned_image(db, current_user, product_id, image_id)
        source_bytes = await CatalogueService._read_image_bytes(image)

        try:
            output_bytes, content_type, width, height = image_processing_service.apply_operations(
                source_bytes, req.operations
            )
        except ValueError as e:
            raise ValidationException(str(e))

        return ImageEditPreviewResponse(
            content_base64=base64.b64encode(output_bytes).decode("ascii"),
            content_type=content_type,
            width=width,
            height=height,
        )

    @staticmethod
    async def save_edit_image(
        db: AsyncSession,
        current_user: User,
        product_id: str,
        image_id: str,
        req: ImageEditRequest,
    ) -> ProductImageResponse:
        """The one step in the editing session that actually persists
        anything. Always creates a brand-new EDITED row pointing at the
        image it was edited from via source_image_id — the source is never
        overwritten, matching this codebase's existing "never update, always
        insert a new variant" convention (see upload_image's docstring)."""
        image = await CatalogueService._get_owned_image(db, current_user, product_id, image_id)
        source_bytes = await CatalogueService._read_image_bytes(image)

        try:
            output_bytes, content_type, _width, _height = image_processing_service.apply_operations(
                source_bytes, req.operations
            )
        except ValueError as e:
            raise ValidationException(str(e))

        extension = "png" if content_type == "image/png" else "jpg"
        file_name = f"edited_{Path(image.file_name).stem}.{extension}"

        provider = get_storage_provider()
        storage_path = await provider.upload(
            tenant_id=current_user.tenant_id,
            file_name=file_name,
            content_type=content_type,
            file_bytes=output_bytes,
        )

        edited = ProductImage(
            id=f"img_{uuid.uuid4().hex[:12]}",
            product_id=product_id,
            tenant_id=current_user.tenant_id,
            variant_type="EDITED",
            source_image_id=image.id,
            storage_path=storage_path,
            file_name=file_name,
            content_type=content_type,
            file_size_bytes=len(output_bytes),
            display_order=0,
            is_primary=False,
            created_by=current_user.id,
        )
        await CatalogueRepository.create_image(db, edited)

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="PRODUCT_IMAGE_EDIT_SAVE",
            target_entity="product_images",
            target_id=edited.id,
            before_state=None,
            after_state={
                "product_id": product_id,
                "source_image_id": image.id,
                "operation_count": len(req.operations),
            },
        )

        await db.commit()
        await db.refresh(edited)

        return CatalogueService._build_image_response(edited, provider)

    # -- Pipeline status (Module 21, Phase 1) --------------------------------
    @staticmethod
    async def get_pipeline_status(
        db: AsyncSession, current_user: User, product_id: str, image_id: str
    ) -> PipelineStatusResponse:
        """Reports which of the 5 named pipeline stages exist for a given
        ORIGINAL image, by walking the existing source_image_id lineage
        Module 20 already built for exactly this purpose — no new table."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        source = await CatalogueRepository.get_image_by_id(db, image_id, current_user.tenant_id)
        if not source or source.product_id != product_id:
            raise ResourceNotFoundException(f"Image ID '{image_id}' not found")
        if source.variant_type != "ORIGINAL":
            raise ValidationException("Pipeline status can only be requested for an original image.")

        provider = get_storage_provider()
        all_images = await CatalogueRepository.get_images_by_product(db, product_id, current_user.tenant_id)
        derived = {img.variant_type: img for img in all_images if img.source_image_id == source.id}

        stages = []
        for variant_type in PIPELINE_STAGES:
            if variant_type == "ORIGINAL":
                match = source
            else:
                match = derived.get(variant_type)
            stages.append(
                PipelineStageStatus(
                    variant_type=variant_type,
                    completed=match is not None,
                    image=(
                        CatalogueService._build_image_response(match, provider)
                        if match
                        else None
                    ),
                )
            )

        return PipelineStatusResponse(
            source_image_id=source.id,
            stages=stages,
            ai_provider_configured=is_ai_provider_configured(),
        )

    # -- Design Studio & Rendering Engine (Phase B) --------------------------
    # Extends Modules 20/21 + Phase A. Nothing above this point changes.
    @staticmethod
    def _build_design_response(design: CatalogueDesign) -> CatalogueDesignResponse:
        return CatalogueDesignResponse(
            id=design.id,
            product_id=design.product_id,
            source_design_id=design.source_design_id,
            name=design.name,
            version=design.version,
            canvas=CanvasDocument.model_validate_json(design.canvas_json),
            template_key=design.template_key,
            created_by=design.created_by,
            created_at=design.created_at,
        )

    @staticmethod
    async def _get_owned_product(db: AsyncSession, current_user: User, product_id: str) -> Product:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        product = await CatalogueRepository.get_product_by_id(db, product_id, current_user.tenant_id)
        if not product:
            raise ResourceNotFoundException(f"Product ID '{product_id}' not found")
        return product

    @staticmethod
    async def _get_owned_design(
        db: AsyncSession, current_user: User, product_id: str, design_id: str
    ) -> CatalogueDesign:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        design = await CatalogueRepository.get_design_by_id(db, design_id, current_user.tenant_id)
        if not design or design.product_id != product_id:
            raise ResourceNotFoundException(f"Design ID '{design_id}' not found")
        return design

    @staticmethod
    async def save_design(
        db: AsyncSession, current_user: User, product_id: str, req: CatalogueDesignSaveRequest
    ) -> CatalogueDesignResponse:
        """The ONLY way a CatalogueDesign row is created directly from a
        canvas document — every call inserts a brand-new version, there is
        no update route. The canvas is stored exactly as submitted (every
        layer independently, nothing flattened) — flattening only happens
        later, and only as a side effect of rendering (see export_design)."""
        await CatalogueService._get_owned_product(db, current_user, product_id)

        version = await CatalogueRepository.get_next_version(db, product_id, current_user.tenant_id)
        design = CatalogueDesign(
            id=f"design_{uuid.uuid4().hex[:12]}",
            tenant_id=current_user.tenant_id,
            product_id=product_id,
            source_design_id=None,
            name=req.name,
            version=version,
            canvas_json=req.canvas.model_dump_json(),
            template_key=req.template_key,
            created_by=current_user.id,
        )
        await CatalogueRepository.create_design(db, design)

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="CATALOGUE_DESIGN_SAVE",
            target_entity="catalogue_designs",
            target_id=design.id,
            before_state=None,
            after_state={"product_id": product_id, "version": version, "layer_count": len(req.canvas.layers)},
        )

        await db.commit()
        await db.refresh(design)
        return CatalogueService._build_design_response(design)

    @staticmethod
    async def get_designs(
        db: AsyncSession, current_user: User, product_id: str
    ) -> List[CatalogueDesignResponse]:
        """Every version, newest first — this listing IS the version
        history (View)."""
        await CatalogueService._get_owned_product(db, current_user, product_id)
        designs = await CatalogueRepository.get_designs_by_product(db, product_id, current_user.tenant_id)
        return [CatalogueService._build_design_response(d) for d in designs]

    @staticmethod
    async def get_design(
        db: AsyncSession, current_user: User, product_id: str, design_id: str
    ) -> CatalogueDesignResponse:
        design = await CatalogueService._get_owned_design(db, current_user, product_id, design_id)
        return CatalogueService._build_design_response(design)

    @staticmethod
    async def _clone_design(
        db: AsyncSession,
        current_user: User,
        product_id: str,
        design_id: str,
        name: Optional[str],
        audit_action: str,
    ) -> CatalogueDesignResponse:
        """Shared mechanic behind Restore and Duplicate — both just insert a
        new version cloned from an existing one's canvas_json; only the
        default naming and the audit trail's action differ."""
        source = await CatalogueService._get_owned_design(db, current_user, product_id, design_id)
        version = await CatalogueRepository.get_next_version(db, product_id, current_user.tenant_id)

        clone = CatalogueDesign(
            id=f"design_{uuid.uuid4().hex[:12]}",
            tenant_id=current_user.tenant_id,
            product_id=product_id,
            source_design_id=source.id,
            name=name,
            version=version,
            canvas_json=source.canvas_json,
            template_key=source.template_key,
            created_by=current_user.id,
        )
        await CatalogueRepository.create_design(db, clone)

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action=audit_action,
            target_entity="catalogue_designs",
            target_id=clone.id,
            before_state={"source_design_id": source.id, "source_version": source.version},
            after_state={"version": version},
        )

        await db.commit()
        await db.refresh(clone)
        return CatalogueService._build_design_response(clone)

    @staticmethod
    async def restore_design(
        db: AsyncSession, current_user: User, product_id: str, design_id: str, req: CatalogueDesignCloneRequest
    ) -> CatalogueDesignResponse:
        """Brings an old version back as the newest version — nothing is
        deleted or overwritten, the old row stays exactly where it was in
        history."""
        source = await CatalogueService._get_owned_design(db, current_user, product_id, design_id)
        name = req.name if req.name is not None else source.name
        return await CatalogueService._clone_design(
            db, current_user, product_id, design_id, name, "CATALOGUE_DESIGN_RESTORE"
        )

    @staticmethod
    async def duplicate_design(
        db: AsyncSession, current_user: User, product_id: str, design_id: str, req: CatalogueDesignCloneRequest
    ) -> CatalogueDesignResponse:
        """Branches a copy of an existing version to edit independently."""
        source = await CatalogueService._get_owned_design(db, current_user, product_id, design_id)
        if req.name is not None:
            name = req.name
        elif source.name:
            name = f"{source.name} (Copy)"
        else:
            name = None
        return await CatalogueService._clone_design(
            db, current_user, product_id, design_id, name, "CATALOGUE_DESIGN_DUPLICATE"
        )

    # -- Rendering ------------------------------------------------------------
    @staticmethod
    def _rescale_canvas(canvas: CanvasDocument, target_w: int, target_h: int) -> CanvasDocument:
        """Lets one saved design render at any Output Preset size without a
        separate per-preset layout — every layer's box is remapped
        proportionally (and TEXT layers' font_size scales with it), reusing
        the exact same render_canvas() pipeline afterward."""
        if target_w == canvas.canvas_width and target_h == canvas.canvas_height:
            return canvas
        scale_x = target_w / canvas.canvas_width
        scale_y = target_h / canvas.canvas_height
        avg_scale = (scale_x + scale_y) / 2
        new_layers = []
        for layer in canvas.layers:
            updates = {
                "x": layer.x * scale_x,
                "y": layer.y * scale_y,
                "width": layer.width * scale_x,
                "height": layer.height * scale_y,
            }
            if layer.font_size:
                updates["font_size"] = layer.font_size * avg_scale
            new_layers.append(layer.model_copy(update=updates))
        return canvas.model_copy(update={"canvas_width": target_w, "canvas_height": target_h, "layers": new_layers})

    @staticmethod
    async def _resolve_product_layers(
        db: AsyncSession, current_user: User, canvas: CanvasDocument, product_id: Optional[str]
    ) -> CanvasDocument:
        """A template's PRODUCT layer(s) carry image_id=None on purpose (see
        catalogue_asset_library.TEMPLATE_PRESETS) so the same template can
        apply to any product. This fills that gap in with the given
        product's own primary image, per-render — the template document
        itself is never mutated in storage."""
        if not product_id:
            return canvas
        needs_resolution = any(l.type == "PRODUCT" and not l.image_id for l in canvas.layers)
        if not needs_resolution:
            return canvas

        product = await CatalogueRepository.get_product_by_id(db, product_id, current_user.tenant_id)
        primary = None
        if product:
            primary = next(
                (i for i in product.images if i.is_primary and i.variant_type == "ORIGINAL"), None
            )
        resolved_layers = [
            layer.model_copy(update={"image_id": primary.id}) if (layer.type == "PRODUCT" and not layer.image_id and primary)
            else layer
            for layer in canvas.layers
        ]
        return canvas.model_copy(update={"layers": resolved_layers})

    @staticmethod
    async def _download_referenced_images(
        db: AsyncSession, current_user: User, canvas: CanvasDocument
    ) -> Dict[str, bytes]:
        provider = get_storage_provider()
        image_ids = {layer.image_id for layer in canvas.layers if layer.image_id}
        images: Dict[str, bytes] = {}
        # Performance: one batched WHERE id IN (...) lookup instead of a
        # query per referenced image — same result set (missing/foreign-
        # tenant ids just aren't in `found`, exactly as get_image_by_id
        # would have returned None for them one at a time).
        found = await CatalogueRepository.get_images_by_ids(db, list(image_ids), current_user.tenant_id)
        found_by_id = {image.id: image for image in found}
        for image_id in image_ids:
            image = found_by_id.get(image_id)
            if not image:
                continue  # render_canvas() shows an honest placeholder for any unresolved reference
            try:
                images[image_id] = await provider.download(image.storage_path)
            except Exception as e:
                logger.warning(f"Could not download referenced image '{image_id}' for render: {e}")
        return images

    @staticmethod
    async def _render(
        db: AsyncSession,
        current_user: User,
        canvas: CanvasDocument,
        product_id: Optional[str] = None,
        output_preset: Optional[str] = None,
        quality: Optional[str] = None,
    ):
        """Shared by preview, export, and batch-render — the one place a
        canvas becomes pixels, so none of those three call sites duplicate
        rendering logic (per the Performance requirements). `quality` is one
        of RENDER_QUALITY_LEVELS' keys (STANDARD/HIGH/ULTRA) — the Product
        Studio's Quality selector — defaulting to DEFAULT_RENDER_QUALITY."""
        resolved = await CatalogueService._resolve_product_layers(db, current_user, canvas, product_id)
        if output_preset:
            dims = OUTPUT_PRESETS[output_preset]
            resolved = CatalogueService._rescale_canvas(resolved, dims["width"], dims["height"])
        images = await CatalogueService._download_referenced_images(db, current_user, resolved)
        quality_level = RENDER_QUALITY_LEVELS.get(quality or DEFAULT_RENDER_QUALITY, RENDER_QUALITY_LEVELS[DEFAULT_RENDER_QUALITY])
        return catalogue_render_service.render_canvas(resolved, images, quality=quality_level)

    @staticmethod
    async def render_preview(
        db: AsyncSession, current_user: User, product_id: str, req: RenderPreviewRequest
    ) -> RenderPreviewResponse:
        """Ephemeral — nothing is persisted, mirroring Phase A's Image Editor
        preview step exactly. Renders an ad-hoc, unsaved canvas (the live
        Design Studio editing session)."""
        await CatalogueService._get_owned_product(db, current_user, product_id)
        try:
            output_bytes, content_type, width, height = await CatalogueService._render(
                db, current_user, req.canvas, product_id, req.output_preset, req.quality
            )
        except ValueError as e:
            raise ValidationException(str(e))

        return RenderPreviewResponse(
            content_base64=base64.b64encode(output_bytes).decode("ascii"),
            content_type=content_type,
            width=width,
            height=height,
        )

    @staticmethod
    async def export_design(
        db: AsyncSession,
        current_user: User,
        product_id: str,
        design_id: str,
        req: ExportDesignRequest,
    ) -> ProductImageResponse:
        """Renders a SAVED design version and persists the flattened result
        as a new ProductImage — the only rendering call that writes
        anything. The CatalogueDesign row itself (and every layer in it)
        is untouched; this only ever adds a new derived image."""
        design = await CatalogueService._get_owned_design(db, current_user, product_id, design_id)
        canvas = CanvasDocument.model_validate_json(design.canvas_json)

        try:
            output_bytes, content_type, _w, _h = await CatalogueService._render(
                db, current_user, canvas, product_id, req.output_preset, req.quality
            )
        except ValueError as e:
            raise ValidationException(str(e))

        variant_type = OUTPUT_PRESET_TO_VARIANT.get(req.output_preset, "TEMPLATE") if req.output_preset else "TEMPLATE"
        return await CatalogueService._persist_rendered_image(
            db, current_user, product_id, output_bytes, content_type, variant_type, design_id
        )

    @staticmethod
    async def _persist_rendered_image(
        db: AsyncSession,
        current_user: User,
        product_id: str,
        output_bytes: bytes,
        content_type: str,
        variant_type: str,
        design_id: Optional[str],
    ) -> ProductImageResponse:
        extension = "png" if content_type == "image/png" else "jpg"
        file_name = f"design_export_{uuid.uuid4().hex[:8]}.{extension}"

        provider = get_storage_provider()
        storage_path = await provider.upload(
            tenant_id=current_user.tenant_id,
            file_name=file_name,
            content_type=content_type,
            file_bytes=output_bytes,
        )

        # source_image_id stays NULL — a design export is composed from
        # potentially many layers/images, not derived from one single
        # parent photo, so ProductImage's existing single-parent lineage
        # field doesn't apply here (same as an ORIGINAL row).
        image = ProductImage(
            id=f"img_{uuid.uuid4().hex[:12]}",
            product_id=product_id,
            tenant_id=current_user.tenant_id,
            variant_type=variant_type,
            source_image_id=None,
            storage_path=storage_path,
            file_name=file_name,
            content_type=content_type,
            file_size_bytes=len(output_bytes),
            display_order=0,
            is_primary=False,
            created_by=current_user.id,
        )
        await CatalogueRepository.create_image(db, image)

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="CATALOGUE_DESIGN_EXPORT",
            target_entity="product_images",
            target_id=image.id,
            before_state=None,
            after_state={"product_id": product_id, "design_id": design_id, "variant_type": variant_type},
        )

        await db.commit()
        await db.refresh(image)

        return CatalogueService._build_image_response(image, provider)

    # -- Templates & Output Presets (static, no DB) --------------------------
    @staticmethod
    def list_templates() -> List[TemplateSummary]:
        return [
            TemplateSummary(
                key=key,
                label=TEMPLATE_LABELS[key],
                canvas=CanvasDocument(**preset),
                category=TEMPLATE_CATEGORIES.get(key),
            )
            for key, preset in TEMPLATE_PRESETS.items()
        ]

    @staticmethod
    def list_output_presets() -> List[OutputPresetSummary]:
        return [
            OutputPresetSummary(key=key, width=dims["width"], height=dims["height"])
            for key, dims in OUTPUT_PRESETS.items()
        ]

    # -- Batch rendering & multi-product catalogue PDF -----------------------
    @staticmethod
    async def _get_owned_products(
        db: AsyncSession, current_user: User, product_ids: List[str]
    ) -> List[Product]:
        """Validates every product up front (all-or-nothing) before
        rendering any of them, so a bad ID in a 50-product batch can't
        leave a partial set of side effects."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        # Performance: one batched WHERE id IN (...) lookup instead of a
        # query per product id. Validation order/semantics are unchanged —
        # still raises on the first missing id in `product_ids` order, with
        # the identical exception and message a per-id lookup would have
        # raised for that same id.
        found = await CatalogueRepository.get_products_by_ids(db, list(set(product_ids)), current_user.tenant_id)
        found_by_id = {product.id: product for product in found}
        products = []
        for product_id in product_ids:
            product = found_by_id.get(product_id)
            if not product:
                raise ResourceNotFoundException(f"Product ID '{product_id}' not found")
            products.append(product)
        return products

    @staticmethod
    def _get_template_canvas(template_key: str) -> CanvasDocument:
        preset = TEMPLATE_PRESETS.get(template_key)
        if not preset:
            raise ValidationException(f"Unknown template_key '{template_key}'.")
        return CanvasDocument(**preset)

    @staticmethod
    async def batch_render(
        db: AsyncSession, current_user: User, req: BatchRenderRequest
    ) -> List[ProductImageResponse]:
        """Renders ONE template across MANY products, synchronously — no
        background job system, per the explicit requirement. Reuses the
        exact same _render()/_persist_rendered_image() path export_design()
        uses for a single product; nothing is duplicated here."""
        products = await CatalogueService._get_owned_products(db, current_user, req.product_ids)
        template_canvas = CatalogueService._get_template_canvas(req.template_key)
        variant_type = (
            OUTPUT_PRESET_TO_VARIANT.get(req.output_preset, "TEMPLATE") if req.output_preset else "TEMPLATE"
        )

        results = []
        for product in products:
            try:
                output_bytes, content_type, _w, _h = await CatalogueService._render(
                    db, current_user, template_canvas, product.id, req.output_preset, req.quality
                )
            except ValueError as e:
                raise ValidationException(str(e))
            image = await CatalogueService._persist_rendered_image(
                db, current_user, product.id, output_bytes, content_type, variant_type, None
            )
            results.append(image)
        return results

    @staticmethod
    async def generate_catalogue_pdf(
        db: AsyncSession, current_user: User, req: CataloguePdfRequest
    ) -> CataloguePdfResponse:
        """Multi-product catalogue PDF — ephemeral, like Module 15's export
        endpoints (base64 in the response, nothing persisted to storage or
        the DB), since a multi-product artifact doesn't belong to any single
        product's ProductImage rows."""
        products = await CatalogueService._get_owned_products(db, current_user, req.product_ids)
        template_canvas = CatalogueService._get_template_canvas(req.template_key)

        pages = []
        for product in products:
            try:
                output_bytes, _content_type, width, height = await CatalogueService._render(
                    db, current_user, template_canvas, product.id, None, req.quality
                )
            except ValueError as e:
                raise ValidationException(str(e))
            pages.append((output_bytes, width, height))

        pdf_bytes = catalogue_render_service.build_pdf_from_images(pages)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"catalogue_{req.template_key.lower()}_{timestamp}.pdf"

        return CataloguePdfResponse(
            filename=filename,
            content_base64=base64.b64encode(pdf_bytes).decode("ascii"),
            product_count=len(products),
        )
