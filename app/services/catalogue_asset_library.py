"""
Jewellery Catalogue & Marketing Studio — Phase B: the reusable asset library
catalogue_render_service.py's pipeline draws on. Everything here is either a
bundled local file (fonts) or a plain Python constant/generator (badge and
overlay "assets" are deliberately NOT pre-rendered static images — see the
note on BADGE_PRESETS/OVERLAY_KEYS below) — no network calls, no AI, nothing
that depends on request-time external state.

Font files live under app/assets/fonts/ (vendored once, at development time,
from Google Fonts' OFL-licensed catalogue — see that folder's NOTICE.txt for
provenance/license text). The app itself never fetches a font over the
network.
"""

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import ImageFont

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

# Three curated families spanning the looks a jewellery catalogue actually
# needs: an elegant serif for luxury/editorial templates, a clean sans for
# everyday product copy, and a script/display face for festive occasions.
# Deliberately small — this is a foundation module, not a font marketplace.
FONT_FAMILIES: Dict[str, Dict[str, object]] = {
    "PLAYFAIR_DISPLAY": {
        "label": "Playfair Display",
        "style": "serif",
        "variable": True,
        "file": "PlayfairDisplay-Variable.ttf",
    },
    "POPPINS": {
        "label": "Poppins",
        "style": "sans-serif",
        "variable": False,
        "files": {
            "REGULAR": "Poppins-Regular.ttf",
            "MEDIUM": "Poppins-Medium.ttf",
            "BOLD": "Poppins-Bold.ttf",
        },
    },
    "GREAT_VIBES": {
        "label": "Great Vibes",
        "style": "script",
        "variable": False,
        "file": "GreatVibes-Regular.ttf",
        # Single weight only — a bold request against this family silently
        # renders at the font's only available weight (documented, not a
        # bug — see the fonts folder's NOTICE.txt).
    },
}

_WEIGHT_TO_VARIABLE_AXIS = {"REGULAR": 400, "MEDIUM": 500, "BOLD": 700}

_font_cache: Dict[str, ImageFont.FreeTypeFont] = {}


def resolve_font(family: Optional[str], weight: Optional[str], size: int) -> ImageFont.FreeTypeFont:
    """
    Loads a bundled font file for the given family/weight/size. Falls back to
    Playfair Display (this library's default) for an unrecognized family
    string, rather than raising — a typo'd or future/unknown font_family in a
    saved design should still render *something* sensible instead of failing
    the whole render.
    """
    family = (family or "PLAYFAIR_DISPLAY").upper()
    weight = (weight or "REGULAR").upper()
    size = max(6, int(size))

    meta = FONT_FAMILIES.get(family, FONT_FAMILIES["PLAYFAIR_DISPLAY"])

    if "files" in meta:  # Poppins-style: real per-weight static files
        file_name = meta["files"].get(weight, meta["files"]["REGULAR"])
        cache_key = f"{file_name}:{size}"
        if cache_key not in _font_cache:
            _font_cache[cache_key] = ImageFont.truetype(str(FONT_DIR / file_name), size)
        return _font_cache[cache_key]

    # Single-file family (Playfair Display's variable font, or a genuinely
    # single-weight family like Great Vibes).
    file_name = meta["file"]
    cache_key = f"{file_name}:{size}"
    if cache_key not in _font_cache:
        _font_cache[cache_key] = ImageFont.truetype(str(FONT_DIR / file_name), size)
    font = _font_cache[cache_key]

    if meta.get("variable"):
        try:
            font.set_variation_by_axes([_WEIGHT_TO_VARIABLE_AXIS.get(weight, 400)])
        except Exception:
            pass  # best-effort — some FreeType builds lack variable-font
            # support; falls back to the font's default instance rather than
            # crashing the render over a typographic nicety.
    return font


# -- Badges -------------------------------------------------------------------
# Badges are drawn programmatically at render time (a rounded pill + label,
# see catalogue_render_service.py's _render_badge) rather than shipped as
# static PNG files. This is a deliberate choice, not a shortcut: a jewellery
# design's badge can be placed at any size the layer's width/height specify,
# and a pre-rendered raster asset would either look blurry when scaled up or
# need a whole set of pre-baked resolutions. A vector-like draw call stays
# crisp at any size and is the more maintainable "reusable asset" for this
# use case — the preset below is the reusable, shared part (colors + label),
# not the pixels.
BADGE_PRESETS: Dict[str, Dict[str, str]] = {
    "22K": {"label": "22K", "bg_color": "#B8860B", "text_color": "#FFFFFF"},
    "916": {"label": "916 HALLMARK", "bg_color": "#B8860B", "text_color": "#FFFFFF"},
    "HALLMARKED": {"label": "HALLMARKED", "bg_color": "#0B1F3A", "text_color": "#FFFFFF"},
    "NEW_ARRIVAL": {"label": "NEW ARRIVAL", "bg_color": "#7A0C2E", "text_color": "#FFFFFF"},
    "BEST_SELLER": {"label": "BEST SELLER", "bg_color": "#1E3A6E", "text_color": "#FFFFFF"},
    "TRENDING": {"label": "TRENDING", "bg_color": "#8A2BE2", "text_color": "#FFFFFF"},
    "LIMITED_EDITION": {"label": "LIMITED EDITION", "bg_color": "#111111", "text_color": "#D4AF37"},
}

# -- Overlays -----------------------------------------------------------------
# Same reasoning as badges: each key names a resolution-independent drawing
# routine in catalogue_render_service.py (border/frame/sparkle/flourish/
# watermark), not a static file. DFX_WATERMARK is how the "Powered by DFX
# Solution" mark is expressed — there is no separate Watermark layer TYPE.
OVERLAY_KEYS: List[str] = [
    "LUXURY_BORDER",
    "PREMIUM_FRAME",
    "SPARKLES",
    "CORNER_FLOURISH",
    "CIRCLE_VIGNETTE",
    "DFX_WATERMARK",
]

DEFAULT_ACCENT_COLOR = "#D4AF37"  # warm gold — this codebase's established luxury/jewellery accent (see Module 21's watermark treatment)

# Product Studio redesign — Quality. A real render parameter (JPEG quality),
# not a cosmetic label — see catalogue_render_service.render_canvas().
RENDER_QUALITY_LEVELS: Dict[str, int] = {
    "STANDARD": 75,
    "HIGH": 92,
    "ULTRA": 100,
}
DEFAULT_RENDER_QUALITY = "HIGH"


# -- Output presets (real marketing-asset sizes, in pixels) -------------------
OUTPUT_PRESETS: Dict[str, Dict[str, int]] = {
    "INSTAGRAM_POST": {"width": 1080, "height": 1080},
    "INSTAGRAM_STORY": {"width": 1080, "height": 1920},
    "WHATSAPP": {"width": 1080, "height": 1080},
    "FACEBOOK": {"width": 1200, "height": 630},
    "POSTER": {"width": 1500, "height": 2100},
    "BANNER": {"width": 1600, "height": 500},
    "SQUARE": {"width": 1080, "height": 1080},
    "PORTRAIT": {"width": 1080, "height": 1350},
    "LANDSCAPE": {"width": 1350, "height": 1080},
}

# Maps an output preset to the ProductImage variant_type its rendered result
# is stored as — reuses the variant slots Module 20/21 already modeled
# (INSTAGRAM/WHATSAPP/FACEBOOK/TEMPLATE), falling back to the generic
# TEMPLATE bucket for presets with no dedicated slot. Same "fall back to a
# shared bucket" precedent ai_enhancement_service.py's ENHANCEMENT_OUTPUT_VARIANT
# already established.
OUTPUT_PRESET_TO_VARIANT: Dict[str, str] = {
    "INSTAGRAM_POST": "INSTAGRAM",
    "INSTAGRAM_STORY": "INSTAGRAM",
    "WHATSAPP": "WHATSAPP",
    "FACEBOOK": "FACEBOOK",
    "POSTER": "TEMPLATE",
    "BANNER": "TEMPLATE",
    "SQUARE": "TEMPLATE",
    "PORTRAIT": "TEMPLATE",
    "LANDSCAPE": "TEMPLATE",
}


# -- Templates ----------------------------------------------------------------
# Each template is just a preloaded CanvasDocument (a plain dict matching
# that schema) — "convert the template previews into real templates" means
# exactly this: the same generic layer pipeline every design uses, seeded
# with a starting background/border/watermark treatment. Nothing here is a
# separate rendering path.

def _background_layer(w: float, h: float, color: Optional[str], gradient_2: Optional[str] = None) -> dict:
    return {
        "id": "layer_background", "type": "BACKGROUND",
        "x": 0, "y": 0, "width": w, "height": h, "z_index": 0,
        "color": color, "gradient_color_2": gradient_2,
    }


def _product_layer(
    w: float, h: float,
    margin_ratio: float = 0.15,
    box: Optional[Tuple[float, float, float, float]] = None,
) -> dict:
    """The product's own box within the canvas.

    `box`, if given, is (x_ratio, y_ratio, w_ratio, h_ratio) — ratios of the
    canvas, so the same composition works at any canvas size. Module 30:
    before this, every template used the single `margin_ratio` path,
    producing an identical centered ~70% box regardless of what kind of
    jewellery was being photographed (see SESSION_HANDOFF.md Module 30's
    root-cause note — this was the reason a ring and a necklace rendered
    into literally the same box). `margin_ratio` stays as the default path
    for the pre-existing general-purpose templates, unchanged; `box` is what
    the new category-specific templates below use to express a composition
    that actually suits that product type — a necklace's tall box on a
    portrait canvas, a ring's small centered box with generous negative
    space, a bracelet's wide box on a landscape canvas, etc.
    """
    if box is not None:
        x_ratio, y_ratio, w_ratio, h_ratio = box
        return {
            "id": "layer_product", "type": "PRODUCT",
            "x": w * x_ratio, "y": h * y_ratio,
            "width": w * w_ratio, "height": h * h_ratio,
            "z_index": 10,
            "image_id": None,
        }
    mw, mh = w * margin_ratio, h * margin_ratio
    return {
        "id": "layer_product", "type": "PRODUCT",
        "x": mw, "y": mh, "width": w - 2 * mw, "height": h - 2 * mh,
        "z_index": 10,
        # Intentionally no image_id — a template is product-agnostic by
        # design. CatalogueService resolves this to the actual product's
        # primary image at render/batch-render time, per product.
        "image_id": None,
    }


def _overlay_layer(w: float, h: float, overlay_key: str, color: Optional[str] = None, z_index: int = 20) -> dict:
    return {
        "id": f"layer_{overlay_key.lower()}", "type": "OVERLAY",
        "x": 0, "y": 0, "width": w, "height": h, "z_index": z_index,
        "overlay_key": overlay_key, "color": color,
    }


def _watermark_layer(w: float, h: float) -> dict:
    return {
        "id": "layer_watermark", "type": "OVERLAY",
        "x": w - 260, "y": h - 46, "width": 240, "height": 30,
        "z_index": 999, "overlay_key": "DFX_WATERMARK",
    }


def _build_template(
    w: float, h: float,
    bg_color: Optional[str] = "#FFFFFF",
    bg_gradient_2: Optional[str] = None,
    overlay_key: Optional[str] = None,
    overlay_color: Optional[str] = None,
    box: Optional[Tuple[float, float, float, float]] = None,
) -> dict:
    layers = [_background_layer(w, h, bg_color, bg_gradient_2), _product_layer(w, h, box=box)]
    if overlay_key:
        layers.append(_overlay_layer(w, h, overlay_key, overlay_color))
    layers.append(_watermark_layer(w, h))
    return {"canvas_width": w, "canvas_height": h, "layers": layers}


TEMPLATE_LABELS: Dict[str, str] = {
    "LUXURY_WHITE": "Luxury White",
    "LUXURY_BLACK": "Luxury Black",
    "ROYAL_BLUE": "Royal Blue",
    "WEDDING": "Wedding",
    "FESTIVAL": "Festival",
    "INSTAGRAM": "Instagram",
    "WHATSAPP": "WhatsApp",
    "SQUARE": "Square",
    "PORTRAIT": "Portrait",
    "LANDSCAPE": "Landscape",
    "NECKLACE_LUXURY_WHITE": "Luxury White",
    "NECKLACE_PREMIUM_MARBLE": "Premium Marble",
    "NECKLACE_DARK_LUXURY": "Dark Luxury",
    "NECKLACE_BRIDAL": "Bridal",
    "RING_CENTERED": "Centered",
    "RING_CIRCULAR_BALANCE": "Circular Balance",
    "RING_LUXURY_BLACK": "Luxury Black",
    "EARRINGS_BALANCED_SPACING": "Balanced Spacing",
    "EARRINGS_ELEGANT": "Elegant",
    "BRACELET_HORIZONTAL": "Horizontal",
    "BRACELET_LUXURY": "Luxury",
    "PENDANT_PORTRAIT": "Portrait",
    "PENDANT_LUXURY": "Luxury",
    "BANGLE_CIRCULAR_SHOWCASE": "Circular Showcase",
    "BANGLE_PREMIUM": "Premium",
    "FULL_BLEED": "Full Bleed (No Frame)",
}

# Module 30: which product category each template is composed for. The
# original 10 templates use one centered ~70% box regardless of product
# shape and are kept unchanged for backward compatibility — existing saved
# CatalogueDesign rows reference these keys by label (see
# SESSION_HANDOFF.md Module 30). The category templates below give each
# jewellery type a composition suited to its actual shape, per the Module
# 30 requirement that "a necklace template should look like a necklace
# catalogue... a ring template should look like a ring catalogue."
TEMPLATE_CATEGORIES: Dict[str, str] = {
    "NECKLACE_LUXURY_WHITE": "NECKLACE",
    "NECKLACE_PREMIUM_MARBLE": "NECKLACE",
    "NECKLACE_DARK_LUXURY": "NECKLACE",
    "NECKLACE_BRIDAL": "NECKLACE",
    "RING_CENTERED": "RING",
    "RING_CIRCULAR_BALANCE": "RING",
    "RING_LUXURY_BLACK": "RING",
    "EARRINGS_BALANCED_SPACING": "EARRINGS",
    "EARRINGS_ELEGANT": "EARRINGS",
    "BRACELET_HORIZONTAL": "BRACELET",
    "BRACELET_LUXURY": "BRACELET",
    "PENDANT_PORTRAIT": "PENDANT",
    "PENDANT_LUXURY": "PENDANT",
    "BANGLE_CIRCULAR_SHOWCASE": "BANGLE",
    "BANGLE_PREMIUM": "BANGLE",
}

TEMPLATE_PRESETS: Dict[str, dict] = {
    "LUXURY_WHITE": _build_template(1080, 1080, bg_color="#FFFFFF", overlay_key="LUXURY_BORDER", overlay_color="#D4AF37"),
    "LUXURY_BLACK": _build_template(1080, 1080, bg_color="#0A0A0A", overlay_key="LUXURY_BORDER", overlay_color="#D4AF37"),
    "ROYAL_BLUE": _build_template(1080, 1080, bg_color="#0B1F3A", bg_gradient_2="#1E3A6E", overlay_key="PREMIUM_FRAME", overlay_color="#D4AF37"),
    "WEDDING": _build_template(1080, 1350, bg_color="#FDEDE4", bg_gradient_2="#F5D6BA", overlay_key="SPARKLES", overlay_color="#D4AF37"),
    "FESTIVAL": _build_template(1080, 1080, bg_color="#7A0C2E", bg_gradient_2="#D4AF37", overlay_key="SPARKLES", overlay_color="#FFFFFF"),
    "INSTAGRAM": _build_template(1080, 1080, bg_color="#FFFFFF"),
    "WHATSAPP": _build_template(1080, 1080, bg_color="#FFFFFF"),
    "SQUARE": _build_template(1080, 1080, bg_color="#FFFFFF"),
    "PORTRAIT": _build_template(1080, 1350, bg_color="#FFFFFF"),
    "LANDSCAPE": _build_template(1350, 1080, bg_color="#FFFFFF"),

    # --- Necklace: portrait canvas, tall centered box so a hanging chain
    # reads naturally instead of being squeezed into a square. ---
    "NECKLACE_LUXURY_WHITE": _build_template(
        1080, 1350, bg_color="#FFFFFF",
        overlay_key="LUXURY_BORDER", overlay_color="#D4AF37",
        box=(0.10, 0.07, 0.80, 0.82),
    ),
    "NECKLACE_PREMIUM_MARBLE": _build_template(
        1080, 1350, bg_color="#F5F5F0", bg_gradient_2="#E4E0D6",
        overlay_key="CORNER_FLOURISH", overlay_color="#B8B2A4",
        box=(0.10, 0.07, 0.80, 0.82),
    ),
    "NECKLACE_DARK_LUXURY": _build_template(
        1080, 1350, bg_color="#0A0A0A",
        overlay_key="LUXURY_BORDER", overlay_color="#D4AF37",
        box=(0.10, 0.07, 0.80, 0.82),
    ),
    "NECKLACE_BRIDAL": _build_template(
        1080, 1350, bg_color="#FDEDE4", bg_gradient_2="#F5D6BA",
        overlay_key="SPARKLES", overlay_color="#D4AF37",
        box=(0.10, 0.07, 0.80, 0.82),
    ),

    # --- Ring: small centered box with generous negative space — a ring
    # filling most of the frame reads as a cheap product shot, not a
    # catalogue image. Circular Balance/Luxury Black add a round vignette
    # accent instead of a rectangular border on an inherently round subject. ---
    "RING_CENTERED": _build_template(
        1080, 1080, bg_color="#FFFFFF",
        box=(0.32, 0.32, 0.36, 0.36),
    ),
    "RING_CIRCULAR_BALANCE": _build_template(
        1080, 1080, bg_color="#FDFDFB", bg_gradient_2="#EDEAE2",
        overlay_key="CIRCLE_VIGNETTE", overlay_color="#D4AF37",
        box=(0.32, 0.32, 0.36, 0.36),
    ),
    "RING_LUXURY_BLACK": _build_template(
        1080, 1080, bg_color="#0A0A0A",
        overlay_key="CIRCLE_VIGNETTE", overlay_color="#D4AF37",
        box=(0.30, 0.30, 0.40, 0.40),
    ),

    # --- Earrings: wide box with generous side margins so a pair reads as
    # a balanced left/right composition rather than crowding the frame. ---
    "EARRINGS_BALANCED_SPACING": _build_template(
        1080, 1080, bg_color="#FFFFFF",
        box=(0.14, 0.16, 0.72, 0.68),
    ),
    "EARRINGS_ELEGANT": _build_template(
        1080, 1080, bg_color="#FBF8F4", bg_gradient_2="#F0E9DD",
        overlay_key="SPARKLES", overlay_color="#D4AF37",
        box=(0.14, 0.16, 0.72, 0.68),
    ),

    # --- Bracelet: landscape canvas, wide horizontal band centered
    # vertically — matches how a bracelet is actually laid out or worn. ---
    "BRACELET_HORIZONTAL": _build_template(
        1350, 1080, bg_color="#FFFFFF",
        box=(0.08, 0.30, 0.84, 0.40),
    ),
    "BRACELET_LUXURY": _build_template(
        1350, 1080, bg_color="#0B1F3A", bg_gradient_2="#1E3A6E",
        overlay_key="LUXURY_BORDER", overlay_color="#D4AF37",
        box=(0.08, 0.30, 0.84, 0.40),
    ),

    # --- Pendant: portrait canvas like a necklace, but a more compact
    # centered box since a pendant alone (no long chain run) is smaller. ---
    "PENDANT_PORTRAIT": _build_template(
        1080, 1350, bg_color="#FFFFFF",
        box=(0.22, 0.15, 0.56, 0.55),
    ),
    "PENDANT_LUXURY": _build_template(
        1080, 1350, bg_color="#0A0A0A",
        overlay_key="LUXURY_BORDER", overlay_color="#D4AF37",
        box=(0.22, 0.15, 0.56, 0.55),
    ),

    # --- Bangle: round subject, square canvas, circular vignette accent —
    # same reasoning as Ring's circular templates. ---
    "BANGLE_CIRCULAR_SHOWCASE": _build_template(
        1080, 1080, bg_color="#FFFFFF",
        overlay_key="CIRCLE_VIGNETTE", overlay_color="#D4AF37",
        box=(0.20, 0.20, 0.60, 0.60),
    ),
    "BANGLE_PREMIUM": _build_template(
        1080, 1080, bg_color="#0B1F3A", bg_gradient_2="#1E3A6E",
        overlay_key="CIRCLE_VIGNETTE", overlay_color="#D4AF37",
        box=(0.20, 0.20, 0.60, 0.60),
    ),

    # --- Full Bleed: no frame, no border, no margin — the product fills the
    # entire canvas (box covers 100%, no overlay). Used as the Product
    # Studio's automatic, invisible default composition now that the
    # user-facing Templates picker has been removed (per explicit user
    # request — see SESSION_HANDOFF.md Module 30): Save Version / Export /
    # Generate PDF / Batch Render all still need SOME CanvasDocument to
    # render against, this is the one that adds nothing on top of the
    # already fully auto-fitted, background-cleaned, cover-fit product
    # photo — just the photo itself, full-bleed, plus the same DFX
    # watermark every other template also carries. ---
    "FULL_BLEED": _build_template(
        1080, 1080, bg_color="#FFFFFF",
        box=(0.0, 0.0, 1.0, 1.0),
    ),
}
