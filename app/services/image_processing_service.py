"""
Jewellery Catalogue & Marketing Studio — Phase A: real, local Image Editor.

Every function in this file is deterministic pixel processing via Pillow and
OpenCV, run entirely in-process. Nothing here calls an external API, requires
a provider key, or depends on a trained ML model — this is the module that
makes crop/rotate/filters/background-replace genuinely work offline, as a
completely separate concern from app/services/ai_enhancement_service.py's
still-unconfigured AIProvider (which stays exactly as it was: an honest stub
for OpenAI/Google/Cloudinary/Replicate/Fal-style semantic enhancement that
this codebase deliberately does not fake).

Background replacement in particular is a classical-CV approximation (corner
color sampling + OpenCV GrabCut refinement), not a trained-model cutout —
clean on the plain-backdrop product photography this feature targets, softer
on busy/reflective backgrounds. That limitation is deliberate and disclosed
in the API layer / UI copy, not silently overpromised.
"""

import io
from typing import Callable, Dict, List, Tuple

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

from app.schemas.catalogue import ImageEditOperation

_LUXURY_BLUE_HEX = "#0B1F3A"

_PRESET_BACKGROUND_COLORS = {
    "WHITE": "#FFFFFF",
    "BLACK": "#000000",
    "LUXURY_BLUE": _LUXURY_BLUE_HEX,
}


def _hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


# -- Individual operations ---------------------------------------------------
# Each handler takes the current PIL Image + its ImageEditOperation params and
# returns the next PIL Image. Kept as small, independently-testable pure
# functions rather than one large branching method.

def _op_crop(img: Image.Image, op: ImageEditOperation) -> Image.Image:
    if op.x is None or op.y is None or op.width is None or op.height is None:
        raise ValueError("CROP requires x, y, width, and height.")
    img_w, img_h = img.size
    if op.x >= img_w or op.y >= img_h:
        raise ValueError("Crop origin is outside the image bounds.")
    right = min(op.x + op.width, img_w)
    bottom = min(op.y + op.height, img_h)
    return img.crop((op.x, op.y, right, bottom))


def _op_rotate(img: Image.Image, op: ImageEditOperation) -> Image.Image:
    if op.degrees is None:
        raise ValueError("ROTATE requires degrees.")
    # expand=True grows the canvas to fit the rotated content instead of
    # clipping corners; the newly-exposed corners become transparent (hence
    # the RGBA conversion) rather than an arbitrary fill color.
    return img.convert("RGBA").rotate(-op.degrees, expand=True, resample=Image.BICUBIC)


def _op_flip(img: Image.Image, op: ImageEditOperation) -> Image.Image:
    if op.axis == "HORIZONTAL":
        return img.transpose(Image.FLIP_LEFT_RIGHT)
    if op.axis == "VERTICAL":
        return img.transpose(Image.FLIP_TOP_BOTTOM)
    raise ValueError("FLIP requires axis to be HORIZONTAL or VERTICAL.")


def _op_brightness(img: Image.Image, op: ImageEditOperation) -> Image.Image:
    return ImageEnhance.Brightness(img).enhance(op.factor if op.factor is not None else 1.0)


def _op_contrast(img: Image.Image, op: ImageEditOperation) -> Image.Image:
    return ImageEnhance.Contrast(img).enhance(op.factor if op.factor is not None else 1.0)


def _op_saturation(img: Image.Image, op: ImageEditOperation) -> Image.Image:
    # ImageEnhance.Color only touches color channels — alpha (if present)
    # passes through untouched.
    return ImageEnhance.Color(img).enhance(op.factor if op.factor is not None else 1.0)


def _op_sharpness(img: Image.Image, op: ImageEditOperation) -> Image.Image:
    return ImageEnhance.Sharpness(img).enhance(op.factor if op.factor is not None else 1.0)


def _op_blur(img: Image.Image, op: ImageEditOperation) -> Image.Image:
    radius = op.radius if op.radius is not None else 2.0
    return img.filter(ImageFilter.GaussianBlur(radius=radius))


def _op_white_balance(img: Image.Image, op: ImageEditOperation) -> Image.Image:
    """Gray-world auto white balance: scales each RGB channel so its mean
    matches the overall gray-level mean. A classical, deterministic
    algorithm — no ML model involved."""
    has_alpha = img.mode == "RGBA"
    alpha = img.getchannel("A") if has_alpha else None
    rgb = img.convert("RGB")
    arr = np.array(rgb).astype(np.float32)
    channel_means = arr.reshape(-1, 3).mean(axis=0)
    gray_mean = channel_means.mean()
    # Guard a near-zero channel mean (e.g. a solid-black test image) from
    # producing an extreme or divide-by-zero scale factor.
    scales = np.array(
        [gray_mean / m if m > 1e-3 else 1.0 for m in channel_means], dtype=np.float32
    )
    arr = np.clip(arr * scales, 0, 255).astype(np.uint8)
    balanced = Image.fromarray(arr, mode="RGB")
    if has_alpha:
        balanced = balanced.convert("RGBA")
        balanced.putalpha(alpha)
    return balanced


def _op_noise_reduction(img: Image.Image, op: ImageEditOperation) -> Image.Image:
    strength = op.strength if op.strength is not None else 10.0
    has_alpha = img.mode == "RGBA"
    alpha = img.getchannel("A") if has_alpha else None
    rgb = img.convert("RGB")
    cv_bgr = cv2.cvtColor(np.array(rgb), cv2.COLOR_RGB2BGR)
    denoised = cv2.fastNlMeansDenoisingColored(
        cv_bgr, None, h=strength, hColor=strength, templateWindowSize=7, searchWindowSize=21
    )
    result = Image.fromarray(cv2.cvtColor(denoised, cv2.COLOR_BGR2RGB), mode="RGB")
    if has_alpha:
        result = result.convert("RGBA")
        result.putalpha(alpha)
    return result


def _estimate_background_color(rgb_arr: np.ndarray) -> np.ndarray:
    """Median color of small patches in all 4 corners — a simple, honest
    approximation of 'what backdrop is this shot against', tuned for the
    plain-backdrop jewellery photography this feature targets."""
    h, w = rgb_arr.shape[:2]
    patch = max(4, min(h, w) // 20)
    corners = [
        rgb_arr[0:patch, 0:patch],
        rgb_arr[0:patch, w - patch:w],
        rgb_arr[h - patch:h, 0:patch],
        rgb_arr[h - patch:h, w - patch:w],
    ]
    samples = np.concatenate([c.reshape(-1, 3) for c in corners], axis=0)
    return np.median(samples, axis=0)


def _build_grabcut_seed_mask(rgb_arr: np.ndarray, bg_color: np.ndarray, threshold: float = 40.0) -> np.ndarray:
    """
    Seeds GrabCut from an actual estimate of *where the subject is*, not a
    fixed assumption that it's centered and roughly half-frame. That fixed
    assumption was the root cause of inconsistent background removal
    (SESSION_HANDOFF.md Module 30): an off-center product left the old
    center-block seed sitting mostly on real background, which GrabCut then
    misread as probable foreground — producing large leftover borders. A
    small product suffered the same failure; a large/asymmetric one could
    have its edges cut off because the fixed block didn't reach them.

    Still classical CV, still deterministic — this is a bounding-box
    estimate from color-distance thresholding (the same technique
    _detect_foreground_bbox already uses elsewhere in this file), not object
    detection via any trained model.
    """
    distance = np.linalg.norm(rgb_arr.astype(np.float32) - bg_color, axis=2)
    mask = np.where(distance < threshold, cv2.GC_PR_BGD, cv2.GC_PR_FGD).astype("uint8")

    h, w = mask.shape
    margin = max(2, min(h, w) // 50)
    mask[0:margin, :] = cv2.GC_BGD
    mask[h - margin:h, :] = cv2.GC_BGD
    mask[:, 0:margin] = cv2.GC_BGD
    mask[:, w - margin:w] = cv2.GC_BGD

    # Locate the subject: bounding box of the LARGEST connected component of
    # pixels far enough from the estimated background color. This is a
    # rough estimate (the same thresholding _detect_foreground_bbox uses),
    # not the final segmentation — GrabCut still refines the real boundary
    # from here. Connected components (not a naive min/max bbox over every
    # far-from-background pixel) matters for two reasons: it stays correct
    # for a small product — a min/max bbox and a connected-component bbox
    # are identical for one solid blob, so nothing is lost there — while
    # also not being fooled by scattered noise/reflection speckles, which a
    # naive min/max bbox would stretch across the whole frame even though
    # each speckle is tiny. It also naturally handles thin or hollow
    # jewellery shapes (a ring's band, a fine chain) correctly: the
    # component's bounding box wraps the object's actual extent regardless
    # of how sparsely it fills that box, unlike a density-based filter
    # (rejected in review — a hollow ring or thin chain legitimately fills
    # well under half its own bbox, so a density floor would wrongly treat
    # real jewellery as noise).
    far_from_bg = distance >= threshold
    image_area = h * w
    bbox = None
    if far_from_bg.any():
        num_labels, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
            far_from_bg.astype(np.uint8), connectivity=8
        )
        if num_labels > 1:  # label 0 is the background component
            largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
            x, y, cw, ch, pixel_count = stats[largest]
            bbox_area = int(cw) * int(ch)
            # Too large (covers almost the whole frame — nothing for a seed
            # box to usefully distinguish) — fall through to the safe
            # center-block default below. The lower bound is deliberately
            # tiny (a handful of pixels, not a % of the frame): a small
            # ring or stud earring shot in a wide frame can legitimately
            # occupy well under 1% of it, and rejecting those bboxes was
            # exactly the "jewellery is too small" failure mode this
            # seeding rewrite was meant to fix (SESSION_HANDOFF.md Module
            # 30) — a percentage floor would have just re-introduced the
            # bug for small products specifically.
            if bbox_area <= 0.97 * image_area and pixel_count >= 25:
                bbox = (int(x), int(y), int(x + cw), int(y + ch))

    if bbox is not None:
        left, top, right, bottom = bbox
        # Shrink 20% inward on each axis before anchoring as *definite*
        # foreground — the rough bbox's own edges are the least reliable
        # part of it (that's exactly what GrabCut is being asked to refine),
        # so anchoring safely inside it avoids seeding definite-foreground
        # on what might actually be background right at the boundary.
        inset_x = round((right - left) * 0.2)
        inset_y = round((bottom - top) * 0.2)
        fx0, fx1 = left + inset_x, right - inset_x
        fy0, fy1 = top + inset_y, bottom - inset_y
        if fx1 <= fx0 or fy1 <= fy0:  # degenerate after shrinking — use the bbox itself
            fx0, fy0, fx1, fy1 = left, top, right, bottom
        mask[fy0:fy1, fx0:fx1] = cv2.GC_FGD
    else:
        # No trustworthy bbox (e.g. a low-contrast or already-tight product
        # shot) — same unconditional center-block anchor as before, purely
        # as a last resort so GrabCut always has at least one FGD sample to
        # work from (it crashes on "bgdSamples.empty() && fgdSamples.empty()"
        # otherwise — see the Phase A bugfix note this replaces).
        cx0, cx1 = w // 4, (3 * w) // 4
        cy0, cy1 = h // 4, (3 * h) // 4
        mask[cy0:cy1, cx0:cx1] = cv2.GC_FGD
    return mask


def _op_background_replace(img: Image.Image, op: ImageEditOperation) -> Image.Image:
    if op.mode is None:
        raise ValueError("BACKGROUND_REPLACE requires mode.")
    if op.mode == "CUSTOM" and not op.color:
        raise ValueError("BACKGROUND_REPLACE mode=CUSTOM requires color.")

    rgb = img.convert("RGB")
    rgb_arr = np.array(rgb)
    h, w = rgb_arr.shape[:2]

    bg_sample = _estimate_background_color(rgb_arr)
    seed_mask = _build_grabcut_seed_mask(rgb_arr, bg_sample)

    bgd_model = np.zeros((1, 65), np.float64)
    fgd_model = np.zeros((1, 65), np.float64)
    cv_bgr = cv2.cvtColor(rgb_arr, cv2.COLOR_RGB2BGR)
    try:
        cv2.grabCut(cv_bgr, seed_mask, None, bgd_model, fgd_model, 5, cv2.GC_INIT_WITH_MASK)
    except cv2.error as e:
        raise ValueError(f"Background segmentation failed: {e}")

    alpha = np.where(
        (seed_mask == cv2.GC_FGD) | (seed_mask == cv2.GC_PR_FGD), 255, 0
    ).astype(np.uint8)
    # Feather the mask edge for a softer, less "cut out with scissors" edge.
    alpha = cv2.GaussianBlur(alpha, (5, 5), 0)

    if op.mode == "TRANSPARENT":
        result = rgb.convert("RGBA")
        result.putalpha(Image.fromarray(alpha, mode="L"))
        return result

    if op.mode == "GRADIENT":
        top = np.array(_hex_to_rgb(op.color or "#FFFFFF"), dtype=np.float32)
        bottom = np.array(_hex_to_rgb(op.gradient_color_2 or op.color or "#CCCCCC"), dtype=np.float32)
        t = np.linspace(0, 1, h, dtype=np.float32).reshape(h, 1, 1)
        background = np.broadcast_to(
            top.reshape(1, 1, 3) * (1 - t) + bottom.reshape(1, 1, 3) * t, (h, w, 3)
        )
    else:
        hex_color = op.color if op.mode == "CUSTOM" else _PRESET_BACKGROUND_COLORS[op.mode]
        background = np.full((h, w, 3), _hex_to_rgb(hex_color), dtype=np.float32)

    alpha_f = (alpha.astype(np.float32) / 255.0)[..., None]
    composited = rgb_arr.astype(np.float32) * alpha_f + background * (1 - alpha_f)
    composited = np.clip(composited, 0, 255).astype(np.uint8)
    return Image.fromarray(composited, mode="RGB")


def _detect_foreground_bbox(img: Image.Image, threshold: float = 40.0) -> "tuple[int, int, int, int]":
    """
    Returns (left, top, right, bottom) of the detected foreground content —
    shared by all three Auto Fit operations below. If the image already has
    meaningful transparency (e.g. from a prior BACKGROUND_REPLACE(TRANSPARENT)
    step), uses the alpha channel directly; otherwise estimates the backdrop
    color from the corners (same technique BACKGROUND_REPLACE uses) and
    thresholds by color distance. Falls back to the full image bounds if no
    foreground pixels are found (e.g. a genuinely solid-color image) — a
    fitting operation on an image with no detectable subject should be a
    safe no-op, not a crash.
    """
    mask = None
    if img.mode == "RGBA":
        alpha = np.array(img.getchannel("A"))
        if alpha.min() < 250:  # meaningful transparency actually exists
            mask = alpha > 16

    if mask is None:
        rgb_arr = np.array(img.convert("RGB"))
        bg_color = _estimate_background_color(rgb_arr)
        distance = np.linalg.norm(rgb_arr.astype(np.float32) - bg_color, axis=2)
        mask = distance >= threshold

    ys, xs = np.where(mask)
    if len(xs) == 0 or len(ys) == 0:
        return 0, 0, img.width, img.height
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _estimated_bg_rgb(img: Image.Image) -> "tuple[int, int, int]":
    median = _estimate_background_color(np.array(img.convert("RGB")))
    return tuple(int(c) for c in median)


def _op_remove_empty_space(img: Image.Image, op: ImageEditOperation) -> Image.Image:
    """Crops to the tightest bounding box around the detected product, plus
    a small padding margin — 'trim the whitespace'."""
    left, top, right, bottom = _detect_foreground_bbox(img)
    padding_ratio = op.padding_ratio if op.padding_ratio is not None else 0.05
    pad_x = round((right - left) * padding_ratio)
    pad_y = round((bottom - top) * padding_ratio)
    left = max(0, left - pad_x)
    top = max(0, top - pad_y)
    right = min(img.width, right + pad_x)
    bottom = min(img.height, bottom + pad_y)
    return img.crop((left, top, right, bottom))


def _op_auto_center(img: Image.Image, op: ImageEditOperation) -> Image.Image:
    """Re-centers the detected product within the SAME canvas size, padding
    with the estimated backdrop color (or transparency, if the source
    already has meaningful alpha) rather than cropping anything away."""
    left, top, right, bottom = _detect_foreground_bbox(img)
    padding_ratio = op.padding_ratio if op.padding_ratio is not None else 0.0
    pad_x = round((right - left) * padding_ratio)
    pad_y = round((bottom - top) * padding_ratio)
    left = max(0, left - pad_x)
    top = max(0, top - pad_y)
    right = min(img.width, right + pad_x)
    bottom = min(img.height, bottom + pad_y)

    content = img.crop((left, top, right, bottom))
    has_alpha = img.mode == "RGBA"
    canvas = (
        Image.new("RGBA", img.size, (0, 0, 0, 0))
        if has_alpha
        else Image.new("RGB", img.size, _estimated_bg_rgb(img))
    )
    paste_x = (img.width - content.width) // 2
    paste_y = (img.height - content.height) // 2
    canvas.paste(content, (paste_x, paste_y), content if has_alpha else None)
    return canvas


def _op_auto_scale(img: Image.Image, op: ImageEditOperation) -> Image.Image:
    """Crops to the detected product, scales it to fill fill_ratio of the
    canvas's shorter dimension (aspect preserved), then centers it —
    Remove Empty Space + a target fill scale + Auto Center in one step."""
    # Module 30 — 0.85 (not 0.8): "the product should occupy approximately
    # 80-90% of the canvas" — this is the default when a caller doesn't
    # specify one; still fully overridable per-call.
    fill_ratio = op.fill_ratio if op.fill_ratio is not None else 0.85
    left, top, right, bottom = _detect_foreground_bbox(img)
    content = img.crop((left, top, right, bottom))

    target_dim = min(img.width, img.height) * fill_ratio
    scale = target_dim / max(content.width, content.height)
    new_w = max(1, round(content.width * scale))
    new_h = max(1, round(content.height * scale))
    resized = content.resize((new_w, new_h), Image.LANCZOS)

    has_alpha = img.mode == "RGBA"
    canvas = (
        Image.new("RGBA", img.size, (0, 0, 0, 0))
        if has_alpha
        else Image.new("RGB", img.size, _estimated_bg_rgb(img))
    )
    paste_x = (img.width - resized.width) // 2
    paste_y = (img.height - resized.height) // 2
    canvas.paste(resized, (paste_x, paste_y), resized if has_alpha else None)
    return canvas


_OPERATION_HANDLERS: Dict[str, Callable[[Image.Image, ImageEditOperation], Image.Image]] = {
    "CROP": _op_crop,
    "ROTATE": _op_rotate,
    "FLIP": _op_flip,
    "BRIGHTNESS": _op_brightness,
    "CONTRAST": _op_contrast,
    "SATURATION": _op_saturation,
    "SHARPNESS": _op_sharpness,
    "BLUR": _op_blur,
    "WHITE_BALANCE": _op_white_balance,
    "NOISE_REDUCTION": _op_noise_reduction,
    "BACKGROUND_REPLACE": _op_background_replace,
    "REMOVE_EMPTY_SPACE": _op_remove_empty_space,
    "AUTO_CENTER": _op_auto_center,
    "AUTO_SCALE": _op_auto_scale,
}


def apply_operations(
    image_bytes: bytes, operations: List[ImageEditOperation]
) -> Tuple[bytes, str, int, int]:
    """
    Applies an ordered list of editing operations to `image_bytes` and
    returns (output_bytes, content_type, width, height).

    Pure function — no DB access, no storage writes, no side effects. The
    caller (CatalogueService) decides whether the result is an ephemeral
    preview or something to actually persist as a new ProductImage row.
    Raises ValueError on any invalid operation/parameter/image — the service
    layer translates this into a ValidationException (400), matching this
    codebase's existing error-handling convention.
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img.load()
    except Exception as e:
        raise ValueError(f"Could not decode image: {e}")

    for op in operations:
        handler = _OPERATION_HANDLERS.get(op.type)
        if handler is None:
            raise ValueError(f"Unsupported operation type '{op.type}'.")
        img = handler(img, op)

    # Only actually emit PNG (with real transparency) if something in the
    # pipeline left a non-opaque pixel — e.g. a rotate's exposed corners or a
    # TRANSPARENT background replace. A rotate-by-360 or a same-size crop
    # shouldn't force every result into a larger PNG file for no reason.
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        if img.getchannel("A").getextrema() == (255, 255):
            img = img.convert("RGB")

    buffer = io.BytesIO()
    if img.mode == "RGBA":
        img.save(buffer, format="PNG")
        content_type = "image/png"
    else:
        img = img.convert("RGB")
        img.save(buffer, format="JPEG", quality=92)
        content_type = "image/jpeg"

    return buffer.getvalue(), content_type, img.width, img.height
