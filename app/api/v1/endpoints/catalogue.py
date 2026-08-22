from typing import Optional
from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.models.auth import User
from app.permissions.dependencies import require_admin_or_staff_module
from app.schemas.auth import StandardSuccessResponse
from app.schemas.catalogue import (
    ProductCreateRequest,
    ProductUpdateRequest,
    ImageReorderRequest,
    EnhancementRequest,
    ImageEditRequest,
    CatalogueDesignSaveRequest,
    CatalogueDesignCloneRequest,
    RenderPreviewRequest,
    ExportDesignRequest,
    BatchRenderRequest,
    CataloguePdfRequest,
)
from app.services.catalogue_service import CatalogueService

router = APIRouter()


# 1. Products
@router.get(
    "/catalogue/products",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="List Products (Admin)",
    description="Returns all products (active and inactive) for the admin's tenant, each with its "
                "image variants. Optional filters: category, purity, sub_category (case-insensitive).",
)
async def list_products(
    category: Optional[str] = Query(None),
    purity: Optional[str] = Query(None),
    sub_category: Optional[str] = Query(None),
    current_user: User = Depends(require_admin_or_staff_module("catalogue")),
    db: AsyncSession = Depends(get_async_db),
):
    products = await CatalogueService.get_products(
        db, current_user, category=category, purity=purity, sub_category=sub_category
    )
    return StandardSuccessResponse(
        success=True,
        message="Products retrieved successfully",
        data={"products": [p.model_dump(mode="json") for p in products]},
    )


@router.get(
    "/catalogue/products/{product_id}",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Product (Admin)",
)
async def get_product(
    product_id: str,
    current_user: User = Depends(require_admin_or_staff_module("catalogue")),
    db: AsyncSession = Depends(get_async_db),
):
    product = await CatalogueService.get_product_by_id(db, current_user, product_id)
    return StandardSuccessResponse(
        success=True,
        message="Product retrieved successfully",
        data={"product": product.model_dump(mode="json")},
    )


@router.post(
    "/catalogue/products",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Product (Admin)",
)
async def create_product(
    req: ProductCreateRequest,
    current_user: User = Depends(require_admin_or_staff_module("catalogue")),
    db: AsyncSession = Depends(get_async_db),
):
    product = await CatalogueService.create_product(db, current_user, req)
    return StandardSuccessResponse(
        success=True,
        message="Product created successfully",
        data={"product": product.model_dump(mode="json")},
    )


@router.put(
    "/catalogue/products/{product_id}",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Product (Admin)",
)
async def update_product(
    product_id: str,
    req: ProductUpdateRequest,
    current_user: User = Depends(require_admin_or_staff_module("catalogue")),
    db: AsyncSession = Depends(get_async_db),
):
    product = await CatalogueService.update_product(db, current_user, product_id, req)
    return StandardSuccessResponse(
        success=True,
        message="Product updated successfully",
        data={"product": product.model_dump(mode="json")},
    )


@router.delete(
    "/catalogue/products/{product_id}",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Deactivate Product (Admin)",
    description="Soft-deletes a product by setting is_active=False. Its images are untouched.",
)
async def deactivate_product(
    product_id: str,
    current_user: User = Depends(require_admin_or_staff_module("catalogue")),
    db: AsyncSession = Depends(get_async_db),
):
    await CatalogueService.deactivate_product(db, current_user, product_id)
    return StandardSuccessResponse(
        success=True, message="Product deactivated successfully", data={}
    )


# 2. Images
@router.post(
    "/catalogue/products/{product_id}/images",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload Product Image (Admin)",
    description="Uploads a new ORIGINAL image for a product. Never overwrites — every upload is a new gallery entry.",
)
async def upload_image(
    product_id: str,
    file: UploadFile = File(...),
    shot_type: Optional[str] = Form(None),
    current_user: User = Depends(require_admin_or_staff_module("catalogue")),
    db: AsyncSession = Depends(get_async_db),
):
    image = await CatalogueService.upload_image(db, current_user, product_id, file, shot_type)
    return StandardSuccessResponse(
        success=True,
        message="Image uploaded successfully",
        data={"image": image.model_dump(mode="json")},
    )


@router.put(
    "/catalogue/products/{product_id}/images/{image_id}/primary",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Set Primary Image (Admin)",
)
async def set_primary_image(
    product_id: str,
    image_id: str,
    current_user: User = Depends(require_admin_or_staff_module("catalogue")),
    db: AsyncSession = Depends(get_async_db),
):
    await CatalogueService.set_primary_image(db, current_user, product_id, image_id)
    return StandardSuccessResponse(success=True, message="Primary image updated", data={})


@router.put(
    "/catalogue/products/{product_id}/images/reorder",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Reorder Product Images (Admin)",
)
async def reorder_images(
    product_id: str,
    req: ImageReorderRequest,
    current_user: User = Depends(require_admin_or_staff_module("catalogue")),
    db: AsyncSession = Depends(get_async_db),
):
    await CatalogueService.reorder_images(db, current_user, product_id, req)
    return StandardSuccessResponse(success=True, message="Image order updated", data={})


@router.delete(
    "/catalogue/products/{product_id}/images/{image_id}",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete Product Image (Admin)",
)
async def delete_image(
    product_id: str,
    image_id: str,
    current_user: User = Depends(require_admin_or_staff_module("catalogue")),
    db: AsyncSession = Depends(get_async_db),
):
    await CatalogueService.delete_image(db, current_user, product_id, image_id)
    return StandardSuccessResponse(success=True, message="Image deleted", data={})


# 3. Media Library
@router.get(
    "/catalogue/media",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Media Library (Admin)",
    description="Every image variant across every product for the admin's tenant.",
)
async def get_media_library(
    current_user: User = Depends(require_admin_or_staff_module("catalogue")),
    db: AsyncSession = Depends(get_async_db),
):
    images = await CatalogueService.get_media_library(db, current_user)
    return StandardSuccessResponse(
        success=True,
        message="Media library retrieved successfully",
        data={"images": [i.model_dump(mode="json") for i in images]},
    )


@router.get(
    "/catalogue/storage-status",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Storage Provider Status (Admin)",
    description="Reports whether uploads are backed by local disk or a configured Supabase Storage bucket.",
)
async def get_storage_status(
    current_user: User = Depends(require_admin_or_staff_module("catalogue")),
):
    result = CatalogueService.get_storage_status()
    return StandardSuccessResponse(
        success=True, message="Storage status retrieved", data=result.model_dump(mode="json")
    )


@router.get(
    "/catalogue/ai-provider-status",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="AI Provider Status (Admin)",
    description="Reports which AI provider (if any) is configured — always 'Stub'/not configured until Module 21's provider architecture is wired to a real vendor.",
)
async def get_ai_provider_status(
    current_user: User = Depends(require_admin_or_staff_module("catalogue")),
):
    result = CatalogueService.get_ai_provider_status()
    return StandardSuccessResponse(
        success=True, message="AI provider status retrieved", data=result.model_dump(mode="json")
    )


# 4. AI Enhancement (extension point — see app/services/ai_enhancement_service.py)
@router.post(
    "/catalogue/products/{product_id}/images/{image_id}/enhance",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Enhance Image with AI (Admin)",
    description=(
        "Real, stable endpoint shape for a future AI provider. No provider is "
        "configured yet — this always returns a clear 'not configured' error, "
        "never a fake success."
    ),
)
async def enhance_image(
    product_id: str,
    image_id: str,
    req: EnhancementRequest,
    current_user: User = Depends(require_admin_or_staff_module("catalogue")),
    db: AsyncSession = Depends(get_async_db),
):
    await CatalogueService.enhance_image(db, current_user, product_id, image_id, req)
    return StandardSuccessResponse(success=True, message="Enhancement queued", data={})


# 4b. Image Editor (Jewellery Catalogue & Marketing Studio, Phase A) — real,
# local Pillow/OpenCV processing, a separate concern from the AI-provider
# extension point above. /edit/preview never persists anything; /edit/save
# is the only call that creates a new (EDITED) ProductImage row.
@router.post(
    "/catalogue/products/{product_id}/images/{image_id}/edit/preview",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Preview Image Edit (Admin)",
    description=(
        "Applies an ordered list of crop/rotate/filter/background-replace "
        "operations and returns the rendered result as base64 — nothing is "
        "written to the database or to storage. Used for the Design "
        "Studio's live preview and its frontend-only undo/redo/reset."
    ),
)
async def preview_edit_image(
    product_id: str,
    image_id: str,
    req: ImageEditRequest,
    current_user: User = Depends(require_admin_or_staff_module("catalogue")),
    db: AsyncSession = Depends(get_async_db),
):
    result = await CatalogueService.preview_edit_image(db, current_user, product_id, image_id, req)
    return StandardSuccessResponse(
        success=True, message="Preview rendered", data=result.model_dump(mode="json")
    )


@router.post(
    "/catalogue/products/{product_id}/images/{image_id}/edit/save",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Save Image Edit (Admin)",
    description=(
        "Applies the same operations list as /edit/preview, but persists the "
        "result as a new EDITED image variant. This is the only step in the "
        "editing session that writes anything — the source image is never "
        "overwritten."
    ),
)
async def save_edit_image(
    product_id: str,
    image_id: str,
    req: ImageEditRequest,
    current_user: User = Depends(require_admin_or_staff_module("catalogue")),
    db: AsyncSession = Depends(get_async_db),
):
    image = await CatalogueService.save_edit_image(db, current_user, product_id, image_id, req)
    return StandardSuccessResponse(
        success=True,
        message="Edited image saved successfully",
        data={"image": image.model_dump(mode="json")},
    )


# 5. Processing pipeline status (Module 21, Phase 1)
@router.get(
    "/catalogue/products/{product_id}/images/{image_id}/pipeline",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Image Processing Pipeline Status (Admin)",
    description=(
        "Reports which of the 5 named pipeline stages (Original, Background "
        "Removed, Enhanced, Luxury Lighting, Final Catalogue Image) exist for "
        "a given original image, by walking the existing source_image_id "
        "lineage — no new table."
    ),
)
async def get_pipeline_status(
    product_id: str,
    image_id: str,
    current_user: User = Depends(require_admin_or_staff_module("catalogue")),
    db: AsyncSession = Depends(get_async_db),
):
    result = await CatalogueService.get_pipeline_status(db, current_user, product_id, image_id)
    return StandardSuccessResponse(
        success=True, message="Pipeline status retrieved", data=result.model_dump(mode="json")
    )


# 6. Design Studio & Rendering Engine (Jewellery Catalogue & Marketing
# Studio, Phase B) — extends Modules 20/21 + Phase A, nothing above this
# point is changed.

# 6a. Templates & Output Presets — static, no DB, no product context.
@router.get(
    "/catalogue/templates",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="List Design Templates (Admin)",
    description="The 10 preset templates (Luxury White/Black, Royal Blue, Wedding, Festival, Instagram, WhatsApp, Square, Portrait, Landscape), each a preloaded, product-agnostic canvas document.",
)
async def list_templates(current_user: User = Depends(require_admin_or_staff_module("catalogue"))):
    templates = CatalogueService.list_templates()
    return StandardSuccessResponse(
        success=True,
        message="Templates retrieved successfully",
        data={"templates": [t.model_dump(mode="json") for t in templates]},
    )


@router.get(
    "/catalogue/output-presets",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="List Output Presets (Admin)",
)
async def list_output_presets(current_user: User = Depends(require_admin_or_staff_module("catalogue"))):
    presets = CatalogueService.list_output_presets()
    return StandardSuccessResponse(
        success=True,
        message="Output presets retrieved successfully",
        data={"presets": [p.model_dump(mode="json") for p in presets]},
    )


# 6b. Designs — per-product, versioned. Every POST /designs creates a new
# immutable version; there is no update route.
@router.post(
    "/catalogue/products/{product_id}/designs",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Save Design (Admin)",
    description="Creates a new immutable CatalogueDesign version for this product. The canvas is stored exactly as submitted — every layer independently, nothing flattened.",
)
async def save_design(
    product_id: str,
    req: CatalogueDesignSaveRequest,
    current_user: User = Depends(require_admin_or_staff_module("catalogue")),
    db: AsyncSession = Depends(get_async_db),
):
    design = await CatalogueService.save_design(db, current_user, product_id, req)
    return StandardSuccessResponse(
        success=True, message="Design saved successfully", data={"design": design.model_dump(mode="json")}
    )


@router.get(
    "/catalogue/products/{product_id}/designs",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="List Design Versions (Admin)",
    description="Every saved version for this product, newest first — this listing is the version history.",
)
async def list_designs(
    product_id: str,
    current_user: User = Depends(require_admin_or_staff_module("catalogue")),
    db: AsyncSession = Depends(get_async_db),
):
    designs = await CatalogueService.get_designs(db, current_user, product_id)
    return StandardSuccessResponse(
        success=True,
        message="Design versions retrieved successfully",
        data={"designs": [d.model_dump(mode="json") for d in designs]},
    )


# Registered BEFORE /designs/{design_id} so the literal "render" segment
# never gets swallowed by the {design_id} path parameter.
@router.post(
    "/catalogue/products/{product_id}/designs/render/preview",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Preview Render (Admin)",
    description="Renders an ad-hoc, unsaved canvas (the live Design Studio editing session) and returns it as base64 — nothing is persisted.",
)
async def render_preview(
    product_id: str,
    req: RenderPreviewRequest,
    current_user: User = Depends(require_admin_or_staff_module("catalogue")),
    db: AsyncSession = Depends(get_async_db),
):
    result = await CatalogueService.render_preview(db, current_user, product_id, req)
    return StandardSuccessResponse(
        success=True, message="Preview rendered", data=result.model_dump(mode="json")
    )


@router.get(
    "/catalogue/products/{product_id}/designs/{design_id}",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Design Version (Admin)",
)
async def get_design(
    product_id: str,
    design_id: str,
    current_user: User = Depends(require_admin_or_staff_module("catalogue")),
    db: AsyncSession = Depends(get_async_db),
):
    design = await CatalogueService.get_design(db, current_user, product_id, design_id)
    return StandardSuccessResponse(
        success=True, message="Design retrieved successfully", data={"design": design.model_dump(mode="json")}
    )


@router.post(
    "/catalogue/products/{product_id}/designs/{design_id}/restore",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Restore Design Version (Admin)",
    description="Brings an old version back as the newest version. Nothing is deleted or overwritten — the restored-from row stays exactly where it was in history.",
)
async def restore_design(
    product_id: str,
    design_id: str,
    req: CatalogueDesignCloneRequest,
    current_user: User = Depends(require_admin_or_staff_module("catalogue")),
    db: AsyncSession = Depends(get_async_db),
):
    design = await CatalogueService.restore_design(db, current_user, product_id, design_id, req)
    return StandardSuccessResponse(
        success=True, message="Design version restored", data={"design": design.model_dump(mode="json")}
    )


@router.post(
    "/catalogue/products/{product_id}/designs/{design_id}/duplicate",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Duplicate Design Version (Admin)",
    description="Branches a copy of an existing version to edit independently, without disturbing the original.",
)
async def duplicate_design(
    product_id: str,
    design_id: str,
    req: CatalogueDesignCloneRequest,
    current_user: User = Depends(require_admin_or_staff_module("catalogue")),
    db: AsyncSession = Depends(get_async_db),
):
    design = await CatalogueService.duplicate_design(db, current_user, product_id, design_id, req)
    return StandardSuccessResponse(
        success=True, message="Design duplicated", data={"design": design.model_dump(mode="json")}
    )


@router.post(
    "/catalogue/products/{product_id}/designs/{design_id}/export",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Export Design (Admin)",
    description="Renders a saved design version and persists the flattened result as a new ProductImage. The saved design itself is untouched — this only ever adds a new derived image.",
)
async def export_design(
    product_id: str,
    design_id: str,
    req: ExportDesignRequest,
    current_user: User = Depends(require_admin_or_staff_module("catalogue")),
    db: AsyncSession = Depends(get_async_db),
):
    image = await CatalogueService.export_design(db, current_user, product_id, design_id, req)
    return StandardSuccessResponse(
        success=True, message="Design exported successfully", data={"image": image.model_dump(mode="json")}
    )


# 6c. Batch rendering & multi-product catalogue PDF — cross-product, so not
# nested under a single /products/{id}.
@router.post(
    "/catalogue/designs/batch-render",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Batch Render Template Across Products (Admin)",
    description="Renders one template for multiple selected products, synchronously (no background job system). Each product's own primary image is resolved into the template's Product layer automatically.",
)
async def batch_render(
    req: BatchRenderRequest,
    current_user: User = Depends(require_admin_or_staff_module("catalogue")),
    db: AsyncSession = Depends(get_async_db),
):
    images = await CatalogueService.batch_render(db, current_user, req)
    return StandardSuccessResponse(
        success=True,
        message=f"Rendered {len(images)} product(s) successfully",
        data={"images": [i.model_dump(mode="json") for i in images]},
    )


@router.post(
    "/catalogue/designs/catalogue-pdf",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate Multi-Product Catalogue PDF (Admin)",
    description="Renders one template across multiple products and assembles one multi-page PDF, returned as base64. Ephemeral — nothing is persisted to storage or the database, same precedent as Module 15's export endpoints.",
)
async def generate_catalogue_pdf(
    req: CataloguePdfRequest,
    current_user: User = Depends(require_admin_or_staff_module("catalogue")),
    db: AsyncSession = Depends(get_async_db),
):
    result = await CatalogueService.generate_catalogue_pdf(db, current_user, req)
    return StandardSuccessResponse(
        success=True, message="Catalogue PDF generated successfully", data=result.model_dump(mode="json")
    )
