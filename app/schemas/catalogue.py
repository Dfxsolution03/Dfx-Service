from datetime import datetime, date
from typing import Optional, List, Literal, Dict, Any
from pydantic import BaseModel, Field, model_validator

ImageVariantType = Literal[
    "ORIGINAL",
    "ENHANCED",
    "BACKGROUND_REMOVED",
    "TEMPLATE",
    "INSTAGRAM",
    "WHATSAPP",
    "PDF",
    "THUMBNAIL",
    # Module 21 — AI Product Studio: two more named stops on the processing
    # pipeline (Original -> Background Removed -> Enhanced -> Luxury
    # Lighting -> Final Catalogue Image -> Marketing Versions), plus one more
    # per-platform marketing variant alongside the existing INSTAGRAM/WHATSAPP.
    "LUXURY_LIGHTING",
    "FINAL_CATALOGUE",
    "FACEBOOK",
    # Jewellery Catalogue & Marketing Studio — Phase A (Image Editor). Output
    # of a real, local (Pillow/OpenCV) crop/rotate/filter/background-replace
    # session, saved via the editor's explicit "Save" step. Distinct from the
    # AI pipeline's ENHANCED/BACKGROUND_REMOVED variants above, which remain
    # tied to the (still unconfigured) AIProvider — this one is genuinely
    # produced today, by our own code, offline.
    "EDITED",
]

# The 7 buttons Module 20 asks for, plus Module 21's SHADOW_CORRECTION — real,
# stable keys the frontend can send today even though no provider is wired in
# yet (see ai_enhancement_service.py). Module 21 groups REMOVE_BACKGROUND as
# its own dedicated Phase-3 feature in the UI, but it's the same request
# shape and the same endpoint — not a separate type or route.
AIEnhancementType = Literal[
    "REMOVE_BACKGROUND",
    "HD_UPSCALE",
    "LUXURY_LIGHTING",
    "DIAMOND_ENHANCEMENT",
    "GOLD_SHINE",
    "REFLECTION_REMOVAL",
    "AUTO_CROP",
    "SHADOW_CORRECTION",
]


# Product Studio redesign — real jewellery commercial fields, added
# additively to Product (see app/models/catalogue.py's own comment on this).
# ShotType stays a plain optional string (not a closed Literal) on the
# request side too, matching category/sku/purity's existing "free text"
# convention — the 7 named shots are a frontend-suggested vocabulary, not a
# DB-enforced enum.
ShotType = Literal["FRONT", "BACK", "SIDE", "TOP", "ANGLE_45", "LIFESTYLE", "MACRO"]


class ProductCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=150)
    description: Optional[str] = Field(None, max_length=2000)
    category: Optional[str] = Field(None, max_length=100)
    sub_category: Optional[str] = Field(None, max_length=100)
    sku: Optional[str] = Field(None, max_length=100)
    purity: Optional[str] = Field(None, max_length=20)
    price: Optional[float] = Field(None, ge=0)
    weight_grams: Optional[float] = Field(None, ge=0)
    tags: List[str] = Field(default_factory=list)
    making_charge_discount_percent: Optional[float] = Field(None, ge=0, le=100)
    making_charge_discount_label: Optional[str] = Field(None, max_length=200)
    # Per-tag colour overrides, e.g. {"BESTSELLER": "#C9A227"}. Persisted as a
    # JSON string in Product.tag_colors — see CatalogueService._format_tag_colors.
    tag_colors: Optional[Dict[str, str]] = None


class ProductUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=150)
    description: Optional[str] = Field(None, max_length=2000)
    category: Optional[str] = Field(None, max_length=100)
    sub_category: Optional[str] = Field(None, max_length=100)
    sku: Optional[str] = Field(None, max_length=100)
    purity: Optional[str] = Field(None, max_length=20)
    price: Optional[float] = Field(None, ge=0)
    weight_grams: Optional[float] = Field(None, ge=0)
    tags: Optional[List[str]] = None
    making_charge_discount_percent: Optional[float] = Field(None, ge=0, le=100)
    making_charge_discount_label: Optional[str] = Field(None, max_length=200)
    # Per-tag colour overrides, e.g. {"BESTSELLER": "#C9A227"}. Persisted as a
    # JSON string in Product.tag_colors — see CatalogueService._format_tag_colors.
    tag_colors: Optional[Dict[str, str]] = None
    is_active: Optional[bool] = None


class ProductImageResponse(BaseModel):
    id: str
    product_id: str
    variant_type: ImageVariantType
    source_image_id: Optional[str] = None
    shot_type: Optional[str] = None
    url: str
    file_name: str
    content_type: str
    file_size_bytes: int
    display_order: int
    is_primary: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ProductResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    sub_category: Optional[str] = None
    sku: Optional[str] = None
    purity: Optional[str] = None
    price: Optional[float] = None
    weight_grams: Optional[float] = None
    tags: List[str] = Field(default_factory=list)
    making_charge_discount_percent: Optional[float] = None
    making_charge_discount_label: Optional[str] = None
    tag_colors: Optional[Dict[str, str]] = None
    is_active: bool
    # Phase 3 — inventory link + pricing snapshot (additive; NULL for standalone
    # manual products created before Phase 3 or without an inventory source).
    inventory_item_id: Optional[str] = None
    pricing_source: Optional[str] = None
    computed_selling_cost: Optional[float] = None
    price_effective_date: Optional[date] = None
    created_by: str
    created_at: datetime
    updated_at: datetime
    images: List[ProductImageResponse] = Field(default_factory=list)
    primary_image_url: Optional[str] = None
    image_count: int = 0

    class Config:
        from_attributes = True


# ─── Phase 3 — Inventory → Catalogue publishing ───

PricingSource = Literal["SELLING_COST", "CATALOGUE_COST"]


class InventoryPublishRequest(BaseModel):
    """Publish (or re-publish) one inventory item to the catalogue.

    SELLING_COST  -> the server calculates the price via BillingCalculationEngine;
                     a client-supplied catalogue_price is REJECTED.
    CATALOGUE_COST-> the admin supplies catalogue_price (any value > 0; no
                     invented lower/upper bound).
    """
    pricing_source: PricingSource
    catalogue_price: Optional[float] = Field(None, ge=0)
    sub_category: Optional[str] = Field(None, max_length=100)
    # Only used for SELLING_COST calculation; mirrors the billing engine default.
    gst_applied: bool = True

    @model_validator(mode="after")
    def _validate_pricing(self) -> "InventoryPublishRequest":
        if self.pricing_source == "CATALOGUE_COST":
            if self.catalogue_price is None or self.catalogue_price <= 0:
                raise ValueError("catalogue_price is required and must be > 0 for CATALOGUE_COST")
        else:  # SELLING_COST — server computes the price; client must not set it
            if self.catalogue_price is not None:
                raise ValueError(
                    "catalogue_price must not be supplied for SELLING_COST; the server calculates it"
                )
        return self


class InventoryBulkPublishItem(InventoryPublishRequest):
    inventory_item_id: str = Field(..., min_length=1)


class InventoryBulkPublishRequest(BaseModel):
    items: List[InventoryBulkPublishItem] = Field(..., min_length=1)


class InventoryPublishFailure(BaseModel):
    inventory_item_id: str
    error: str


class InventoryBulkPublishResponse(BaseModel):
    published: List[ProductResponse] = Field(default_factory=list)
    failed: List[InventoryPublishFailure] = Field(default_factory=list)
    published_count: int = 0
    failed_count: int = 0


class ImageReorderRequest(BaseModel):
    # Ordered list of image IDs, front-to-back — the index in this list
    # becomes each image's new display_order.
    image_ids: List[str] = Field(..., min_length=1)


class EnhancementRequest(BaseModel):
    enhancement_type: AIEnhancementType


class StorageStatusResponse(BaseModel):
    """Lets the admin UI show an honest banner instead of a silent failure
    when a real Supabase Storage bucket hasn't been configured yet."""
    provider: Literal["local_disk", "supabase"]
    configured: bool


class AIProviderStatusResponse(BaseModel):
    """Module 21 — same pattern as StorageStatusResponse: lets the AI
    Enhancement tab show a dynamic, honest banner instead of an assumed
    static one."""
    provider: str
    configured: bool


# Module 21 — the 5 named pipeline stops between an original and a finished
# catalogue image, in order. Purely a display/UX ordering — reuses the
# existing ProductImage.source_image_id lineage (Module 20) to determine
# which stages actually exist for a given original; no new table.
PIPELINE_STAGES: List[ImageVariantType] = [
    "ORIGINAL",
    "BACKGROUND_REMOVED",
    "ENHANCED",
    "LUXURY_LIGHTING",
    "FINAL_CATALOGUE",
]


class PipelineStageStatus(BaseModel):
    variant_type: ImageVariantType
    completed: bool
    image: Optional[ProductImageResponse] = None


class PipelineStatusResponse(BaseModel):
    source_image_id: str
    stages: List[PipelineStageStatus]
    ai_provider_configured: bool


# =============================================================================
# Jewellery Catalogue & Marketing Studio — Phase A: real, local Image Editor.
# Everything below is deterministic Pillow/OpenCV pixel processing — no AI
# provider, no external service. Reuses the existing ProductImage/variant_type
# storage model; adds no new table.
#
# Session model (per the approved architecture refinement): Original Image ->
# Editing Session (ephemeral, client-held operations list) -> Preview
# (rendered on demand, never persisted) -> Save (persisted exactly once, as a
# new EDITED ProductImage row). Every intermediate adjustment the user makes
# while editing is NOT written to the DB — only the final Save operation is.
# =============================================================================

ImageEditOperationType = Literal[
    "CROP",
    "ROTATE",
    "FLIP",
    "BRIGHTNESS",
    "CONTRAST",
    "SATURATION",
    "SHARPNESS",
    "BLUR",
    "WHITE_BALANCE",
    "NOISE_REDUCTION",
    "BACKGROUND_REPLACE",
    # Product Studio redesign — Auto Fit. All three are classical-CV,
    # deterministic bounding-box operations (corner-color sampling to find
    # the foreground region, same technique BACKGROUND_REPLACE already
    # uses) — no AI/ML involved. See image_processing_service.py.
    "REMOVE_EMPTY_SPACE",
    "AUTO_CENTER",
    "AUTO_SCALE",
]

FlipAxis = Literal["HORIZONTAL", "VERTICAL"]

# GRADIENT/CUSTOM read `color` (and `gradient_color_2` for GRADIENT);
# WHITE/BLACK/LUXURY_BLUE/TRANSPARENT are fixed presets and ignore `color`.
BackgroundReplaceMode = Literal["WHITE", "BLACK", "LUXURY_BLUE", "GRADIENT", "TRANSPARENT", "CUSTOM"]

_HEX_COLOR_PATTERN = r"^#[0-9A-Fa-f]{6}$"


class ImageEditOperation(BaseModel):
    """
    One step in an editing session. Kept as a single flexible shape (only the
    fields relevant to `type` are read) rather than a discriminated union per
    operation — matches this codebase's existing preference for plain
    BaseModel schemas over more elaborate Pydantic constructs (see
    EnhancementRequest above).
    """
    type: ImageEditOperationType

    # CROP — pixel coordinates, top-left origin, against the image's current
    # (post-previous-operation) dimensions.
    x: Optional[int] = Field(None, ge=0)
    y: Optional[int] = Field(None, ge=0)
    width: Optional[int] = Field(None, gt=0)
    height: Optional[int] = Field(None, gt=0)

    # ROTATE — degrees, positive = clockwise. Any value; not restricted to
    # 90-degree steps.
    degrees: Optional[float] = None

    # FLIP
    axis: Optional[FlipAxis] = None

    # BRIGHTNESS / CONTRAST / SATURATION / SHARPNESS — PIL ImageEnhance
    # convention: 1.0 = unchanged, <1.0 decreases, >1.0 increases.
    factor: Optional[float] = Field(None, ge=0, le=3)

    # BLUR — Gaussian blur radius in pixels.
    radius: Optional[float] = Field(None, ge=0, le=50)

    # NOISE_REDUCTION — maps to OpenCV fastNlMeansDenoisingColored's `h`
    # (filter strength). WHITE_BALANCE takes no parameters (gray-world
    # auto-correction).
    strength: Optional[float] = Field(None, ge=0, le=30)

    # BACKGROUND_REPLACE
    mode: Optional[BackgroundReplaceMode] = None
    color: Optional[str] = Field(None, pattern=_HEX_COLOR_PATTERN)
    gradient_color_2: Optional[str] = Field(None, pattern=_HEX_COLOR_PATTERN)

    # REMOVE_EMPTY_SPACE / AUTO_CENTER — extra margin kept around the
    # detected foreground bounding box, as a fraction of that box's size.
    padding_ratio: Optional[float] = Field(None, ge=0, le=1)

    # AUTO_SCALE — target fraction of the canvas's shorter dimension the
    # foreground content should fill after scaling (e.g. 0.8 = 80%).
    fill_ratio: Optional[float] = Field(None, gt=0, le=1)


class ImageEditRequest(BaseModel):
    operations: List[ImageEditOperation] = Field(..., min_length=1)


class ImageEditPreviewResponse(BaseModel):
    """Ephemeral — nothing here is persisted to the DB or to storage. Lets
    the Design Studio's editing session show an instant, accurate preview
    (undo/redo/reset all stay frontend-only against this same operations
    list) before the user commits with an explicit Save."""
    content_base64: str
    content_type: str
    width: int
    height: int


# =============================================================================
# Jewellery Catalogue & Marketing Studio — Phase B: Design Studio & Rendering
# Engine. Extends Modules 20/21 + Phase A — nothing above this point is
# changed or replaced.
#
# The canvas is a GENERIC layered document, not a fixed per-template schema:
# every design (however different its look) is just an ordered list of
# CanvasLayer objects. This is deliberate per the approved architecture
# refinement — a future module can introduce a new layer TYPE or a new
# per-type field without a schema redesign, the same way ProductImage's
# variant_type is a plain string rather than a closed DB enum (see
# app/models/catalogue.py's own docstring on that convention). `props` below
# is the same idea applied to layers: a forward-compatible catch-all so a
# not-yet-invented layer type/field can ride along in the JSON without
# breaking validation of the 8 types this phase actually implements.
# =============================================================================

LayerType = Literal[
    "BACKGROUND", "PRODUCT", "TEXT", "LOGO", "BADGE", "QR", "OVERLAY", "SHAPE"
]

TextAlign = Literal["LEFT", "CENTER", "RIGHT"]
FontWeight = Literal["REGULAR", "MEDIUM", "BOLD"]
ShapeKind = Literal["RECTANGLE", "CIRCLE", "LINE"]


class LayerShadow(BaseModel):
    color: str = Field(default="#000000", pattern=_HEX_COLOR_PATTERN)
    blur: float = Field(default=4.0, ge=0, le=40)
    offset_x: float = 2.0
    offset_y: float = 2.0


class CanvasLayer(BaseModel):
    """
    One layer in a CatalogueDesign's canvas. Every layer carries the same
    common transform fields regardless of type; only the fields relevant to
    `type` are read at render time (same flexible-shape convention as
    ImageEditOperation above) — kept as one model rather than a discriminated
    union per type so a layer can gain a new optional field without touching
    every other layer type's schema.
    """
    id: str
    type: LayerType
    x: float = 0
    y: float = 0
    width: float = Field(default=100, gt=0)
    height: float = Field(default=100, gt=0)
    rotation: float = 0
    scale: float = Field(default=1.0, gt=0, le=5)
    opacity: float = Field(default=1.0, ge=0, le=1)
    visible: bool = True
    locked: bool = False
    z_index: int = 0

    # BACKGROUND (image mode) / PRODUCT / LOGO — references a ProductImage
    # (any image already in the tenant's Media Library, including a
    # separately-uploaded jeweller logo — no new "logo" concept is modeled;
    # this reuses the existing image infrastructure as-is).
    image_id: Optional[str] = None

    # BACKGROUND (solid/gradient) fill, TEXT color, SHAPE fill/stroke, and an
    # optional accent-color override for OVERLAY presets.
    color: Optional[str] = Field(None, pattern=_HEX_COLOR_PATTERN)
    gradient_color_2: Optional[str] = Field(None, pattern=_HEX_COLOR_PATTERN)

    # TEXT
    text: Optional[str] = Field(None, max_length=200)
    font_family: Optional[str] = None
    font_size: Optional[float] = Field(None, gt=0, le=400)
    font_weight: Optional[FontWeight] = None
    text_align: Optional[TextAlign] = None
    letter_spacing: Optional[float] = Field(None, ge=-10, le=50)
    shadow: Optional[LayerShadow] = None

    # BADGE — one of catalogue_asset_library.BADGE_PRESETS' keys.
    badge_key: Optional[str] = None

    # OVERLAY — one of catalogue_asset_library.OVERLAY_KEYS (also how the
    # "Powered by DFX Solution" watermark is expressed: overlay_key=
    # "DFX_WATERMARK" — there is no separate Watermark layer TYPE, per the
    # 8 types this phase defines).
    overlay_key: Optional[str] = None

    # QR — arbitrary payload (typically a product deep link), generated
    # fresh at render time, never stored as a static asset.
    qr_payload: Optional[str] = Field(None, max_length=2000)

    # SHAPE
    shape_kind: Optional[ShapeKind] = None

    # Forward-compatible catch-all — see the module-level docstring above.
    props: Dict[str, Any] = Field(default_factory=dict)


class CanvasDocument(BaseModel):
    canvas_width: float = Field(..., gt=0, le=6000)
    canvas_height: float = Field(..., gt=0, le=6000)
    layers: List[CanvasLayer] = Field(default_factory=list)


# -- CatalogueDesign (versioned canvas documents) ----------------------------

class CatalogueDesignSaveRequest(BaseModel):
    """Every call creates a brand-new immutable version — there is no update
    route for an existing CatalogueDesign row."""
    name: Optional[str] = Field(None, max_length=150)
    canvas: CanvasDocument
    template_key: Optional[str] = None


class CatalogueDesignResponse(BaseModel):
    id: str
    product_id: str
    source_design_id: Optional[str] = None
    name: Optional[str] = None
    version: int
    canvas: CanvasDocument
    template_key: Optional[str] = None
    created_by: str
    created_at: datetime


class CatalogueDesignCloneRequest(BaseModel):
    """Shared body for both /restore and /duplicate — both create a new
    version cloned from an existing one; only the audit action and default
    naming differ (see CatalogueService)."""
    name: Optional[str] = Field(None, max_length=150)


# -- Rendering ----------------------------------------------------------------

OutputPresetKey = Literal[
    "INSTAGRAM_POST", "INSTAGRAM_STORY", "WHATSAPP", "FACEBOOK",
    "POSTER", "BANNER", "SQUARE", "PORTRAIT", "LANDSCAPE",
]

# Product Studio redesign — Quality. Maps to render_canvas()'s JPEG quality
# parameter (see catalogue_asset_library.RENDER_QUALITY_LEVELS) — a real,
# functional render parameter, not a cosmetic label.
RenderQuality = Literal["STANDARD", "HIGH", "ULTRA"]


class RenderPreviewRequest(BaseModel):
    """Ephemeral, like ImageEditPreviewResponse's Preview step — nothing is
    persisted. `canvas` renders an ad-hoc, unsaved document (the live Design
    Studio editing session); pass output_preset to render at a specific
    marketing size instead of the canvas's own declared dimensions."""
    canvas: CanvasDocument
    output_preset: Optional[OutputPresetKey] = None
    quality: Optional[RenderQuality] = None


class RenderPreviewResponse(BaseModel):
    content_base64: str
    content_type: str
    width: int
    height: int


class ExportDesignRequest(BaseModel):
    """Renders a SAVED design version to a final flattened image and persists
    it as a new ProductImage — the only rendering call that writes anything."""
    output_preset: Optional[OutputPresetKey] = None
    quality: Optional[RenderQuality] = None


class TemplateSummary(BaseModel):
    key: str
    label: str
    canvas: CanvasDocument
    category: Optional[str] = None


class OutputPresetSummary(BaseModel):
    key: str
    width: int
    height: int


class BatchRenderRequest(BaseModel):
    """Renders ONE template across MANY products, synchronously (no
    background job system — see catalogue_service.py). Each product's
    PRODUCT-type layer(s) get that product's own primary image resolved in
    automatically; everything else in the template is shared."""
    template_key: str
    product_ids: List[str] = Field(..., min_length=1, max_length=50)
    output_preset: Optional[OutputPresetKey] = None
    quality: Optional[RenderQuality] = None


class CataloguePdfRequest(BaseModel):
    """Multi-product catalogue PDF — one file, many products. Ephemeral like
    Module 15's export endpoints (base64 in the response, nothing persisted
    to storage/DB), reusing that exact precedent rather than inventing a new
    artifact-storage concept for a file that doesn't belong to one product."""
    template_key: str
    product_ids: List[str] = Field(..., min_length=1, max_length=50)
    quality: Optional[RenderQuality] = None


class CataloguePdfResponse(BaseModel):
    filename: str
    content_type: Literal["application/pdf"] = "application/pdf"
    content_base64: str
    product_count: int
