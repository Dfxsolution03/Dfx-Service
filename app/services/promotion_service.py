import uuid
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.models.promotion import Promotion, BANNER_TYPE_IMAGE_ONLY, BANNER_TYPE_STANDARD
from app.repositories.promotion_repository import PromotionRepository
from app.repositories.customer_repository import CustomerRepository
from app.repositories.audit_repository import AuditRepository
from app.exceptions.base import (
    ResourceNotFoundException,
    ForbiddenException,
    ValidationException,
)
from app.services.storage_service import get_storage_provider
from app.schemas.promotion import (
    PromotionCreateRequest,
    PromotionUpdateRequest,
    PromotionResponse,
    CustomerBannerResponse,
)


def _to_response(promotion: Promotion) -> PromotionResponse:
    return PromotionResponse.model_validate(promotion)


class PromotionService:
    # ─── Customer ───

    @staticmethod
    async def get_home_banner(
        db: AsyncSession, current_user: User
    ) -> Optional[CustomerBannerResponse]:
        """Highest-priority active banner for the customer's tenant, or None
        if none exists — never fabricated, never raises for a missing banner."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        promotion = await PromotionRepository.get_top_active_for_tenant(db, current_user.tenant_id)
        if not promotion:
            return None

        tenant = await CustomerRepository.get_tenant_by_id(db, current_user.tenant_id)

        return CustomerBannerResponse(
            id=promotion.id,
            banner_type=promotion.banner_type,
            title=promotion.title,
            subtitle=promotion.subtitle,
            description=promotion.description,
            image_url=promotion.image_url,
            button_text=promotion.button_text,
            button_link=promotion.button_link,
            background_color=promotion.background_color,
            text_color=promotion.text_color,
            store_name=tenant.name if tenant else None,
            store_logo_url=tenant.logo_url if tenant else None,
        )

    # ─── Admin ───

    @staticmethod
    async def list_promotions(db: AsyncSession, current_user: User) -> List[PromotionResponse]:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        promotions = await PromotionRepository.list_by_tenant(db, current_user.tenant_id)
        return [_to_response(p) for p in promotions]

    @staticmethod
    async def create_promotion(
        db: AsyncSession, current_user: User, req: PromotionCreateRequest
    ) -> PromotionResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        data = req.model_dump()
        banner_type = data.get("banner_type") or BANNER_TYPE_STANDARD
        if banner_type == BANNER_TYPE_IMAGE_ONLY:
            # The image is the whole banner.  When is_active=False the caller is
            # staging the record to obtain a promotion ID before uploading the
            # image file (the upload endpoint requires an existing ID).  Requiring
            # image_url at create-time when the promotion is inactive would make
            # that two-phase flow impossible.
            #
            # Invariant preserved by:
            #   • update_promotion: validates image_url before any activation.
            #   • get_top_active_for_tenant: only returns is_active=True rows.
            #
            # Attempted active creation (or update) without an image is still rejected.
            if data.get("is_active", True) and not (data.get("image_url") or "").strip():
                raise ValidationException("An Image-Only banner requires a banner image.")
            data["title"] = ""  # NOT NULL column; image carries all copy
        else:
            if not (data.get("title") or "").strip():
                raise ValidationException("A Standard banner requires a title.")

        promotion_id = f"promo_{uuid.uuid4().hex[:12]}"
        promotion = Promotion(
            id=promotion_id,
            tenant_id=current_user.tenant_id,
            **data,
        )
        await PromotionRepository.create(db, promotion)
        await db.flush()

        # At most one active banner per tenant: the exclusivity UPDATE runs in
        # the same transaction as the insert, so a racing activation cannot
        # slip a second active row past it.
        if promotion.is_active:
            await PromotionRepository.deactivate_others(db, current_user.tenant_id, promotion_id)

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="PROMOTION_CREATE",
            target_entity="promotions",
            target_id=promotion_id,
            before_state=None,
            after_state=req.model_dump(mode="json"),
        )

        await db.commit()
        await db.refresh(promotion)
        return _to_response(promotion)

    @staticmethod
    async def update_promotion(
        db: AsyncSession, current_user: User, promotion_id: str, req: PromotionUpdateRequest
    ) -> PromotionResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        promotion = await PromotionRepository.get_by_id_for_tenant(
            db, promotion_id, current_user.tenant_id
        )
        if not promotion:
            raise ResourceNotFoundException(f"Promotion ID '{promotion_id}' not found")

        updates = req.model_dump(exclude_unset=True)
        before_state = {k: getattr(promotion, k) for k in updates}

        for field, value in updates.items():
            setattr(promotion, field, value)

        # Validate the resulting state (post-merge), not just the incoming diff,
        # so switching type or clearing the image can't leave an invalid banner.
        if promotion.banner_type == BANNER_TYPE_IMAGE_ONLY:
            if not (promotion.image_url or "").strip():
                raise ValidationException("An Image-Only banner requires a banner image.")
            promotion.title = ""
        else:
            if not (promotion.title or "").strip():
                raise ValidationException("A Standard banner requires a title.")

        after_state = {k: getattr(promotion, k) for k in updates}

        await db.flush()
        # Same single-active-banner rule as create — enforced backend-side in
        # this transaction rather than trusted to the admin UI.
        if promotion.is_active:
            await PromotionRepository.deactivate_others(db, current_user.tenant_id, promotion_id)

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="PROMOTION_UPDATE",
            target_entity="promotions",
            target_id=promotion_id,
            before_state=_jsonable(before_state),
            after_state=_jsonable(after_state),
        )

        await db.commit()
        await db.refresh(promotion)
        return _to_response(promotion)

    @staticmethod
    async def upload_image(
        db: AsyncSession,
        current_user: User,
        promotion_id: str,
        file_bytes: bytes,
        file_name: str,
        content_type: str,
    ) -> PromotionResponse:
        """Mirrors the inventory item image upload: same content-type guard,
        same storage provider, and the resolved public URL is persisted on the
        promotion's existing image_url field so records saved with a manually
        typed URL keep working unchanged."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        promotion = await PromotionRepository.get_by_id_for_tenant(
            db, promotion_id, current_user.tenant_id
        )
        if not promotion:
            raise ResourceNotFoundException(f"Promotion ID '{promotion_id}' not found")
        if content_type not in ("image/jpeg", "image/png", "image/webp"):
            raise ValidationException(
                f"Unsupported image type '{content_type}'. Allowed: JPEG, PNG, WebP."
            )

        provider = get_storage_provider()
        storage_path = await provider.upload(
            tenant_id=current_user.tenant_id,
            file_name=file_name,
            content_type=content_type,
            file_bytes=file_bytes,
        )
        image_url = provider.get_public_url(storage_path)
        promotion.image_url = image_url

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="PROMOTION_IMAGE_UPLOAD",
            target_entity="promotions",
            target_id=promotion_id,
            before_state=None,
            after_state={"image_url": image_url},
        )

        await db.commit()
        await db.refresh(promotion)
        return _to_response(promotion)

    @staticmethod
    async def delete_promotion(db: AsyncSession, current_user: User, promotion_id: str) -> None:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        promotion = await PromotionRepository.get_by_id_for_tenant(
            db, promotion_id, current_user.tenant_id
        )
        if not promotion:
            raise ResourceNotFoundException(f"Promotion ID '{promotion_id}' not found")

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="PROMOTION_DELETE",
            target_entity="promotions",
            target_id=promotion_id,
            before_state={"title": promotion.title},
            after_state=None,
        )

        await PromotionRepository.delete(db, promotion)
        await db.commit()


def _jsonable(state: dict) -> dict:
    """Audit logs are JSON-serialized (see AuditLog.before_state/after_state)
    — datetimes must be stringified before that happens."""
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in state.items()}
