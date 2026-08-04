"""
Jewellery Catalogue & Marketing Studio — Phase B: the rendering engine.

Takes a generic layered CanvasDocument (see CanvasLayer/CanvasDocument in
app/schemas/catalogue.py) and composites every layer through ONE pipeline
into a final flattened image. Every layer type — Background, Product, Text,
Logo, Badge, QR, Overlay, Shape — goes through the exact same
"render the layer's own content -> resize/rotate/opacity -> composite onto
the canvas" path; there is no special-cased per-type placement logic. This
is what "everything should render through one pipeline" means in practice.

Nothing here is flattened except the FINAL output of render_canvas() itself.
The CanvasDocument passed in (and the CatalogueDesign row it came from) keeps
every layer fully independent and editable — Product, Text, Badge, QR, Logo,
and Overlay layers are never merged into each other in storage, only in this
one-way render step.

Pure function apart from the bytes it's handed: image_id references
(Product/Logo/Background-image layers) must already be resolved into raw
bytes by the caller (CatalogueService) before calling render_canvas() — this
file has no DB or storage dependency, mirroring image_processing_service.py's
own "pure function" convention from Phase A.
"""

import io
import random
from typing import Dict, List, Optional, Tuple

import numpy as np
import qrcode
from PIL import Image, ImageDraw, ImageFilter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as pdf_canvas

from app.schemas.catalogue import CanvasDocument, CanvasLayer
from app.services.catalogue_asset_library import BADGE_PRESETS, DEFAULT_ACCENT_COLOR, resolve_font
from app.services.image_processing_service import _detect_foreground_bbox


def _hex_to_rgb(hex_color: Optional[str], default: str = "#000000") -> Tuple[int, int, int]:
    h = (hex_color or default).lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _fit_cover(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Resize+crop preserving aspect ratio to fill the box exactly — used for
    every photographic layer (Product/Logo/Background-as-image) so real
    photos never get stretched/distorted, unlike a plain .resize()."""
    target_w, target_h = max(1, int(target_w)), max(1, int(target_h))
    src_w, src_h = img.size
    scale = max(target_w / src_w, target_h / src_h)
    new_w, new_h = max(1, round(src_w * scale)), max(1, round(src_h * scale))
    resized = img.resize((new_w, new_h), Image.LANCZOS)
    left, top = (new_w - target_w) // 2, (new_h - target_h) // 2
    return resized.crop((left, top, left + target_w, top + target_h))


# -- Per-layer-type renderers -------------------------------------------------
# Each returns a fully self-contained RGBA image sized to the layer's own
# (width, height) box — placement (scale/rotate/opacity/position) is handled
# uniformly afterward by _place_layer(), not by these functions.

def _render_background(layer: CanvasLayer, images: Dict[str, bytes]) -> Image.Image:
    w, h = max(1, int(layer.width)), max(1, int(layer.height))
    if layer.image_id and layer.image_id in images:
        source = Image.open(io.BytesIO(images[layer.image_id])).convert("RGB")
        return _fit_cover(source, w, h).convert("RGBA")
    if layer.gradient_color_2:
        top = np.array(_hex_to_rgb(layer.color, "#FFFFFF"), dtype=np.float32)
        bottom = np.array(_hex_to_rgb(layer.gradient_color_2), dtype=np.float32)
        t = np.linspace(0, 1, h, dtype=np.float32).reshape(h, 1, 1)
        rgb = np.broadcast_to(top.reshape(1, 1, 3) * (1 - t) + bottom.reshape(1, 1, 3) * t, (h, w, 3))
        rgba = np.dstack([rgb, np.full((h, w, 1), 255, dtype=np.float32)]).astype(np.uint8)
        return Image.fromarray(rgba, mode="RGBA")
    return Image.new("RGBA", (w, h), _hex_to_rgb(layer.color, "#FFFFFF") + (255,))


def _render_image_layer(layer: CanvasLayer, images: Dict[str, bytes]) -> Image.Image:
    """Product and Logo layers — both are just 'place this image, cover-fit'.

    Module 30: the source is trimmed to its own tight foreground bounding
    box *before* the cover-fit, not fed in as-is. Without this, a source
    that already carries negative-space padding around the subject — most
    commonly Auto Fit's own AUTO_SCALE, which deliberately leaves ~15%
    breathing room around the product for the editor preview — gets that
    padding treated as "real photo content" by _fit_cover: it cover-fits
    the whole padded canvas into the template's product box, so the
    product itself ends up occupying only ~85% of that box instead of
    filling it, compounding with the box's own margin and making the
    product look noticeably smaller in a template than the un-templated
    preview (the exact "After preview is worse than the original" bug
    report — see SESSION_HANDOFF.md Module 30). The template box's own
    margin/coverage ratio is the single intended source of framing space;
    trimming here makes that true regardless of how much incidental
    padding the source image happens to carry. A well-cropped source photo
    (near-zero existing padding) is unaffected — the trim is a no-op.
    """
    w, h = max(1, int(layer.width)), max(1, int(layer.height))
    if not layer.image_id or layer.image_id not in images:
        # An honest, visible placeholder rather than crashing the whole
        # render over one missing/unresolved image reference (e.g. a
        # template's Product layer that a caller forgot to resolve).
        placeholder = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(placeholder).rectangle([2, 2, w - 3, h - 3], outline=(180, 180, 180, 255), width=2)
        return placeholder
    source = Image.open(io.BytesIO(images[layer.image_id]))
    source = source.convert("RGBA") if source.mode in ("RGBA", "LA", "P") else source.convert("RGB")
    left, top, right, bottom = _detect_foreground_bbox(source)
    if right > left and bottom > top:
        source = source.crop((left, top, right, bottom))
    return _fit_cover(source.convert("RGB"), w, h).convert("RGBA")


def _render_text(layer: CanvasLayer) -> Image.Image:
    w, h = max(1, int(layer.width)), max(1, int(layer.height))
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    text = layer.text or ""
    if not text:
        return canvas

    font = resolve_font(layer.font_family, layer.font_weight, int(layer.font_size or 32))
    spacing = layer.letter_spacing or 0
    draw = ImageDraw.Draw(canvas)
    char_widths = [draw.textlength(ch, font=font) for ch in text]
    total_width = sum(char_widths) + spacing * max(0, len(text) - 1)

    if layer.text_align == "CENTER":
        start_x = (w - total_width) / 2
    elif layer.text_align == "RIGHT":
        start_x = w - total_width
    else:
        start_x = 0.0
    ascent, descent = font.getmetrics()
    start_y = (h - (ascent + descent)) / 2

    def _draw_run(target_draw: ImageDraw.ImageDraw, x_offset: float, y_offset: float, fill) -> None:
        cursor = start_x + x_offset
        for ch, cw in zip(text, char_widths):
            target_draw.text((cursor, start_y + y_offset), ch, font=font, fill=fill)
            cursor += cw + spacing

    if layer.shadow:
        shadow_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        _draw_run(
            ImageDraw.Draw(shadow_layer),
            layer.shadow.offset_x, layer.shadow.offset_y,
            _hex_to_rgb(layer.shadow.color) + (255,),
        )
        if layer.shadow.blur > 0:
            shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(layer.shadow.blur))
        canvas = Image.alpha_composite(canvas, shadow_layer)
        draw = ImageDraw.Draw(canvas)

    _draw_run(draw, 0, 0, _hex_to_rgb(layer.color, "#000000") + (255,))
    return canvas


def _render_badge(layer: CanvasLayer) -> Image.Image:
    w, h = max(1, int(layer.width)), max(1, int(layer.height))
    preset = BADGE_PRESETS.get(layer.badge_key or "", BADGE_PRESETS["22K"])
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle([0, 0, w - 1, h - 1], radius=min(w, h) // 4, fill=_hex_to_rgb(preset["bg_color"]) + (235,))

    font = resolve_font("POPPINS", "BOLD", max(10, int(h * 0.42)))
    label = preset["label"]
    text_w = draw.textlength(label, font=font)
    ascent, descent = font.getmetrics()
    draw.text(
        ((w - text_w) / 2, (h - (ascent + descent)) / 2),
        label, font=font, fill=_hex_to_rgb(preset["text_color"]) + (255,),
    )
    return canvas


def _render_qr(layer: CanvasLayer) -> Image.Image:
    w, h = max(1, int(layer.width)), max(1, int(layer.height))
    payload = layer.qr_payload or ""
    if not payload:
        return Image.new("RGBA", (w, h), (0, 0, 0, 0))
    qr = qrcode.QRCode(border=1, box_size=10)
    qr.add_data(payload)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGBA")
    return qr_img.resize((w, h), Image.NEAREST)


def _render_overlay(layer: CanvasLayer) -> Image.Image:
    w, h = max(1, int(layer.width)), max(1, int(layer.height))
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    accent = _hex_to_rgb(layer.color, DEFAULT_ACCENT_COLOR) + (255,)
    key = layer.overlay_key or "LUXURY_BORDER"

    if key == "LUXURY_BORDER":
        inset = max(8, min(w, h) // 40)
        draw.rectangle([inset, inset, w - inset - 1, h - inset - 1], outline=accent, width=3)
        inset2 = inset + 10
        draw.rectangle([inset2, inset2, w - inset2 - 1, h - inset2 - 1], outline=accent, width=1)

    elif key == "PREMIUM_FRAME":
        inset = max(10, min(w, h) // 30)
        corner = max(30, min(w, h) // 8)
        for cx, cy, dx, dy in [
            (inset, inset, 1, 1), (w - inset, inset, -1, 1),
            (inset, h - inset, 1, -1), (w - inset, h - inset, -1, -1),
        ]:
            draw.line([(cx, cy), (cx + dx * corner, cy)], fill=accent, width=4)
            draw.line([(cx, cy), (cx, cy + dy * corner)], fill=accent, width=4)

    elif key == "SPARKLES":
        # Seeded by the layer's own id, not global randomness — the same
        # saved design must sparkle identically every time it's re-rendered
        # (e.g. re-exporting an old CatalogueDesign version), not roll new
        # random positions each time.
        rng = random.Random(layer.id)
        count = max(6, (w * h) // 25000)
        for _ in range(count):
            cx, cy = rng.uniform(0, w), rng.uniform(0, h)
            size = rng.uniform(4, 12)
            draw.line([(cx - size, cy), (cx + size, cy)], fill=accent, width=2)
            draw.line([(cx, cy - size), (cx, cy + size)], fill=accent, width=2)

    elif key == "CIRCLE_VIGNETTE":
        # Module 30 — a thin, centered double-ring accent for round-product
        # templates (Ring "Circular Balance", Bangle "Circular Showcase")
        # rather than a rectangular border on an inherently round subject.
        cx, cy = w / 2, h / 2
        r_outer = min(w, h) * 0.46
        r_inner = r_outer - 14
        draw.ellipse([cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer], outline=accent, width=3)
        draw.ellipse([cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner], outline=accent, width=1)

    elif key == "CORNER_FLOURISH":
        r = max(20, min(w, h) // 10)
        for cx, cy, start in [(0, 0, 0), (w, 0, 90), (w, h, 180), (0, h, 270)]:
            draw.arc([cx - r, cy - r, cx + r, cy + r], start, start + 90, fill=accent, width=3)

    elif key == "DFX_WATERMARK":
        font = resolve_font("POPPINS", "MEDIUM", max(12, int(h * 0.55)))
        text = "Powered by DFX Solution"
        text_w = draw.textlength(text, font=font)
        ascent, descent = font.getmetrics()
        tx, ty = max(0.0, w - text_w), (h - (ascent + descent)) / 2
        # Outline in black + white fill so the watermark stays legible on
        # both light and dark template backgrounds without needing to
        # sample the underlying canvas.
        for ox, oy in [(-1, -1), (1, -1), (-1, 1), (1, 1)]:
            draw.text((tx + ox, ty + oy), text, font=font, fill=(0, 0, 0, 160))
        draw.text((tx, ty), text, font=font, fill=(255, 255, 255, 200))

    return canvas


def _render_shape(layer: CanvasLayer) -> Image.Image:
    w, h = max(1, int(layer.width)), max(1, int(layer.height))
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    fill = _hex_to_rgb(layer.color, "#000000") + (255,)
    kind = layer.shape_kind or "RECTANGLE"
    if kind == "CIRCLE":
        draw.ellipse([0, 0, w - 1, h - 1], fill=fill)
    elif kind == "LINE":
        draw.line([(0, h // 2), (w, h // 2)], fill=fill, width=max(1, h // 10))
    else:
        draw.rectangle([0, 0, w - 1, h - 1], fill=fill)
    return canvas


_LAYER_RENDERERS = {
    "BACKGROUND": _render_background,
    "PRODUCT": _render_image_layer,
    "LOGO": _render_image_layer,
    "TEXT": lambda layer, _images: _render_text(layer),
    "BADGE": lambda layer, _images: _render_badge(layer),
    "QR": lambda layer, _images: _render_qr(layer),
    "OVERLAY": lambda layer, _images: _render_overlay(layer),
    "SHAPE": lambda layer, _images: _render_shape(layer),
}


def _place_layer(base: Image.Image, layer_img: Image.Image, layer: CanvasLayer) -> None:
    """Uniform placement step every layer type goes through identically:
    scale -> rotate (around the box's own center) -> opacity -> composite."""
    scale = layer.scale or 1.0
    effective_w = max(1, round(layer.width * scale))
    effective_h = max(1, round(layer.height * scale))
    if (effective_w, effective_h) != layer_img.size:
        layer_img = layer_img.resize((effective_w, effective_h), Image.LANCZOS)

    if layer.rotation:
        layer_img = layer_img.rotate(-layer.rotation, expand=True, resample=Image.BICUBIC)

    if layer.opacity < 1.0:
        alpha = layer_img.getchannel("A").point(lambda a: int(a * max(0.0, layer.opacity)))
        layer_img.putalpha(alpha)

    center_x = layer.x + layer.width * scale / 2
    center_y = layer.y + layer.height * scale / 2
    paste_x = round(center_x - layer_img.width / 2)
    paste_y = round(center_y - layer_img.height / 2)

    layer_canvas = Image.new("RGBA", base.size, (0, 0, 0, 0))
    layer_canvas.paste(layer_img, (paste_x, paste_y), layer_img)
    base.alpha_composite(layer_canvas)


def render_canvas(
    canvas: CanvasDocument,
    image_bytes_by_id: Optional[Dict[str, bytes]] = None,
    quality: int = 92,
) -> Tuple[bytes, str, int, int]:
    """
    The one rendering pipeline every layer type goes through: render the
    layer's own content, then resize/rotate/opacity-adjust/composite it onto
    a shared canvas, in ascending z_index order (hidden layers skipped).

    Returns (jpeg_bytes, content_type, width, height). The output is always a
    flattened, opaque JPEG — unlike Phase A's Image Editor (which may need to
    preserve transparency for further editing), a Design Studio export is a
    finished marketing asset meant to be viewed/shared directly, so there is
    no reason to carry an alpha channel into the final file.

    `quality` is a real JPEG compression parameter (0-100) — Product Studio's
    Quality selector (Standard/High/Ultra) maps to this via
    catalogue_asset_library.RENDER_QUALITY_LEVELS; the default (92) matches
    this function's original hardcoded value for any caller that doesn't
    care.
    """
    image_bytes_by_id = image_bytes_by_id or {}
    width, height = max(1, int(canvas.canvas_width)), max(1, int(canvas.canvas_height))
    base = Image.new("RGBA", (width, height), (255, 255, 255, 255))

    for layer in sorted(canvas.layers, key=lambda l: l.z_index):
        if not layer.visible:
            continue
        renderer = _LAYER_RENDERERS.get(layer.type)
        if renderer is None:
            raise ValueError(f"Unsupported layer type '{layer.type}'.")
        layer_img = renderer(layer, image_bytes_by_id)
        _place_layer(base, layer_img, layer)

    buffer = io.BytesIO()
    base.convert("RGB").save(buffer, format="JPEG", quality=max(1, min(100, quality)))
    return buffer.getvalue(), "image/jpeg", width, height


def build_pdf_from_images(pages: List[Tuple[bytes, int, int]]) -> bytes:
    """
    Multi-product catalogue PDF (Phase B, requirement #10) — one page per
    already-rendered product image, each page sized to that image's own
    pixel dimensions (1 px = 1 pt; simple and correct for a full-bleed page,
    not a print-shop-grade DPI-aware layout — a reasonable simplification
    for a foundation module, flagged here rather than silently assumed).
    Pure function: takes already-rendered JPEG bytes (from render_canvas()),
    has no DB/storage dependency of its own.
    """
    buffer = io.BytesIO()
    pdf = pdf_canvas.Canvas(buffer)
    for image_bytes, width, height in pages:
        pdf.setPageSize((width, height))
        pdf.drawImage(ImageReader(io.BytesIO(image_bytes)), 0, 0, width=width, height=height)
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()
