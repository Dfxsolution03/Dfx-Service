"""
DFX Solution Service Tests — Image Processing Service
(Jewellery Catalogue & Marketing Studio, Phase A)
=========================================================

Pure unit tests, no DB — image_processing_service is domain-agnostic (image
bytes + an operations list in, image bytes out), so it's tested in isolation
from CatalogueService, storage, and the API layer. Every test uses a
genuinely decodable, in-memory-generated image (never the fake byte strings
Module 20/21's catalogue fixtures use) since Pillow/OpenCV must actually be
able to process it.
"""

import io

import numpy as np
import pytest
from PIL import Image, ImageDraw

from app.schemas.catalogue import ImageEditOperation
from app.services.image_processing_service import apply_operations


def _solid_bytes(size=(200, 200), color=(180, 120, 60), fmt="JPEG") -> bytes:
    img = Image.new("RGB", size, color=color)
    buffer = io.BytesIO()
    img.save(buffer, format=fmt)
    return buffer.getvalue()


def _noisy_bytes(size=(160, 160), seed=42) -> bytes:
    """A smooth gradient (real photographic structure) plus additive
    Gaussian noise — representative of an actual noisy photo. Pure
    per-pixel-random noise (no underlying structure at all) isn't a fair
    test of fastNlMeansDenoising: with no self-similar patches to average
    against, NLM has nothing to denoise toward and barely moves the needle."""
    rng = np.random.default_rng(seed)
    gradient = np.linspace(0, 60, size[0], dtype=np.float32)
    base = np.full((size[1], size[0], 3), 130, dtype=np.float32) + gradient[np.newaxis, :, np.newaxis]
    noise = rng.normal(0, 25, size=base.shape).astype(np.float32)
    arr = np.clip(base + noise, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr, mode="RGB")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def _product_on_backdrop_bytes(
    size=(160, 160), bg_color=(255, 255, 255), fg_color=(20, 20, 20)
) -> bytes:
    """A plain-backdrop product photo stand-in: a solid-color square (the
    'jewellery') centered on a solid-color background — exactly the scenario
    BACKGROUND_REPLACE's classical-CV approximation targets."""
    img = Image.new("RGB", size, color=bg_color)
    draw = ImageDraw.Draw(img)
    margin = size[0] // 4
    draw.rectangle([margin, margin, size[0] - margin, size[1] - margin], fill=fg_color)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def _decode(output_bytes: bytes) -> Image.Image:
    return Image.open(io.BytesIO(output_bytes))


class TestCrop:
    def test_crop_produces_requested_dimensions(self):
        source = _solid_bytes(size=(200, 200))
        output, content_type, width, height = apply_operations(
            source, [ImageEditOperation(type="CROP", x=10, y=20, width=80, height=60)]
        )
        assert (width, height) == (80, 60)
        assert _decode(output).size == (80, 60)
        assert content_type == "image/jpeg"

    def test_crop_missing_params_raises(self):
        source = _solid_bytes()
        with pytest.raises(ValueError):
            apply_operations(source, [ImageEditOperation(type="CROP", x=0, y=0)])

    def test_crop_origin_outside_bounds_raises(self):
        source = _solid_bytes(size=(100, 100))
        with pytest.raises(ValueError):
            apply_operations(
                source, [ImageEditOperation(type="CROP", x=500, y=500, width=10, height=10)]
            )


class TestRotate:
    def test_rotate_expands_canvas_and_stays_lossless_png(self):
        source = _solid_bytes(size=(100, 100))
        output, content_type, width, height = apply_operations(
            source, [ImageEditOperation(type="ROTATE", degrees=45)]
        )
        # expand=True on a 45-degree rotation must grow the canvas.
        assert width > 100 and height > 100
        # Newly-exposed corners are transparent, so this must be a real PNG,
        # not silently forced into an opaque JPEG.
        assert content_type == "image/png"
        assert _decode(output).mode == "RGBA"

    def test_rotate_by_zero_stays_opaque_jpeg(self):
        """A rotate that introduces no transparency shouldn't force every
        result into a larger PNG for no reason."""
        source = _solid_bytes(size=(100, 100), fmt="JPEG")
        output, content_type, _w, _h = apply_operations(
            source, [ImageEditOperation(type="ROTATE", degrees=0)]
        )
        assert content_type == "image/jpeg"


class TestFlip:
    def test_flip_horizontal_mirrors_asymmetric_image(self):
        img = Image.new("RGB", (100, 100), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, 20, 100], fill=(10, 10, 10))  # dark strip on the LEFT
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")

        output, _content_type, _w, _h = apply_operations(
            buffer.getvalue(), [ImageEditOperation(type="FLIP", axis="HORIZONTAL")]
        )
        result = _decode(output).convert("RGB")
        # The dark strip should now be on the RIGHT.
        assert result.getpixel((5, 50))[0] > 200
        assert result.getpixel((95, 50))[0] < 50

    def test_flip_requires_axis(self):
        source = _solid_bytes()
        with pytest.raises(ValueError):
            apply_operations(source, [ImageEditOperation(type="FLIP")])


class TestColorAdjustments:
    def test_brightness_zero_produces_black_image(self):
        source = _solid_bytes(color=(200, 150, 100))
        output, _ct, _w, _h = apply_operations(
            source, [ImageEditOperation(type="BRIGHTNESS", factor=0.0)]
        )
        pixel = _decode(output).convert("RGB").getpixel((10, 10))
        assert pixel == (0, 0, 0)

    def test_saturation_zero_produces_grayscale(self):
        source = _solid_bytes(color=(200, 50, 50))
        output, _ct, _w, _h = apply_operations(
            source, [ImageEditOperation(type="SATURATION", factor=0.0)]
        )
        r, g, b = _decode(output).convert("RGB").getpixel((10, 10))
        assert abs(r - g) <= 2 and abs(g - b) <= 2

    def test_contrast_factor_one_is_a_no_op(self):
        source = _solid_bytes(color=(180, 120, 60))
        output, _ct, _w, _h = apply_operations(
            source, [ImageEditOperation(type="CONTRAST", factor=1.0)]
        )
        assert _decode(output).convert("RGB").getpixel((10, 10)) == (180, 120, 60)

    def test_sharpness_runs_without_error_and_preserves_size(self):
        source = _solid_bytes(size=(120, 120))
        output, _ct, width, height = apply_operations(
            source, [ImageEditOperation(type="SHARPNESS", factor=2.0)]
        )
        assert (width, height) == (120, 120)
        assert _decode(output).size == (120, 120)


class TestBlur:
    def test_blur_reduces_high_frequency_variance(self):
        source = _noisy_bytes()
        output, _ct, _w, _h = apply_operations(
            source, [ImageEditOperation(type="BLUR", radius=6.0)]
        )
        original_arr = np.array(Image.open(io.BytesIO(source)).convert("L"), dtype=np.float32)
        blurred_arr = np.array(_decode(output).convert("L"), dtype=np.float32)
        assert blurred_arr.std() < original_arr.std()


class TestWhiteBalance:
    def test_corrects_a_strong_color_cast(self):
        # A gray image with a heavy red tint — gray-world should pull the
        # channel means back toward each other.
        source = _solid_bytes(color=(220, 120, 110), fmt="PNG")
        output, _ct, _w, _h = apply_operations(
            source, [ImageEditOperation(type="WHITE_BALANCE")]
        )
        arr = np.array(_decode(output).convert("RGB"), dtype=np.float32)
        means = arr.reshape(-1, 3).mean(axis=0)
        assert (means.max() - means.min()) < 5.0  # near-flat after correction


class TestNoiseReduction:
    def test_reduces_variance_on_noisy_image(self):
        source = _noisy_bytes()
        output, _ct, _w, _h = apply_operations(
            source, [ImageEditOperation(type="NOISE_REDUCTION", strength=15.0)]
        )
        original_arr = np.array(Image.open(io.BytesIO(source)).convert("L"), dtype=np.float32)
        denoised_arr = np.array(_decode(output).convert("L"), dtype=np.float32)
        assert denoised_arr.std() < original_arr.std()


class TestBackgroundReplace:
    def test_transparent_mode_produces_alpha_channel(self):
        source = _product_on_backdrop_bytes()
        output, content_type, _w, _h = apply_operations(
            source, [ImageEditOperation(type="BACKGROUND_REPLACE", mode="TRANSPARENT")]
        )
        assert content_type == "image/png"
        result = _decode(output)
        assert result.mode == "RGBA"
        alpha = np.array(result.getchannel("A"))
        # Corners (background) should end up mostly transparent, center
        # (the 'product') mostly opaque — an honest classical-CV
        # approximation, not a pixel-perfect cutout, so this checks the
        # broad direction rather than an exact mask.
        h, w = alpha.shape
        assert alpha[5, 5] < 128
        assert alpha[h // 2, w // 2] > 128

    def test_custom_solid_color_replaces_background(self):
        source = _product_on_backdrop_bytes(bg_color=(255, 255, 255))
        output, content_type, _w, _h = apply_operations(
            source,
            [ImageEditOperation(type="BACKGROUND_REPLACE", mode="CUSTOM", color="#0B1F3A")],
        )
        assert content_type == "image/jpeg"
        result = _decode(output).convert("RGB")
        corner = result.getpixel((2, 2))
        # Corner should now be close to the requested luxury-blue, not white.
        assert corner[2] > corner[0]  # more blue than red

    def test_custom_mode_requires_color(self):
        source = _product_on_backdrop_bytes()
        with pytest.raises(ValueError):
            apply_operations(source, [ImageEditOperation(type="BACKGROUND_REPLACE", mode="CUSTOM")])

    def test_gradient_mode_varies_top_to_bottom(self):
        source = _product_on_backdrop_bytes(size=(160, 160))
        output, _ct, _w, _h = apply_operations(
            source,
            [
                ImageEditOperation(
                    type="BACKGROUND_REPLACE",
                    mode="GRADIENT",
                    color="#FFFFFF",
                    gradient_color_2="#000000",
                )
            ],
        )
        result = _decode(output).convert("RGB")
        top_corner = result.getpixel((2, 2))
        bottom_corner = result.getpixel((2, 157))
        assert sum(top_corner) > sum(bottom_corner)  # white-ish top, black-ish bottom


class TestApplyOperationsChain:
    def test_chained_operations_run_in_order_without_error(self):
        source = _product_on_backdrop_bytes(size=(200, 200))
        output, content_type, width, height = apply_operations(
            source,
            [
                ImageEditOperation(type="CROP", x=10, y=10, width=180, height=180),
                ImageEditOperation(type="ROTATE", degrees=10),
                ImageEditOperation(type="BRIGHTNESS", factor=1.1),
                ImageEditOperation(type="CONTRAST", factor=1.05),
            ],
        )
        assert content_type in ("image/jpeg", "image/png")
        assert _decode(output).size == (width, height)

    def test_undecodable_bytes_raise_value_error(self):
        with pytest.raises(ValueError):
            apply_operations(b"not-an-image", [ImageEditOperation(type="BRIGHTNESS", factor=1.0)])

    def test_unsupported_axis_value_is_rejected_by_schema(self):
        with pytest.raises(Exception):
            ImageEditOperation(type="FLIP", axis="DIAGONAL")


class TestAutoFit:
    """Product Studio redesign — Auto Fit. Classical-CV bounding-box
    detection (corner-color sampling, same technique BACKGROUND_REPLACE
    already uses), no AI/ML involved."""

    def _off_center_product_bytes(self, size=(300, 300), bg=(255, 255, 255), fg=(20, 20, 20)):
        """A small foreground square placed in one corner, NOT centered —
        so Auto Center/Auto Scale actually have visible work to do."""
        img = Image.new("RGB", size, color=bg)
        draw = ImageDraw.Draw(img)
        draw.rectangle([10, 10, 70, 70], fill=fg)
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        return buffer.getvalue()

    def test_remove_empty_space_shrinks_canvas_to_content(self):
        source = self._off_center_product_bytes(size=(300, 300))
        output, _ct, width, height = apply_operations(
            source, [ImageEditOperation(type="REMOVE_EMPTY_SPACE", padding_ratio=0.0)]
        )
        assert width < 300 and height < 300
        assert _decode(output).size == (width, height)

    def test_remove_empty_space_on_solid_image_is_safe_no_op(self):
        """No detectable foreground (a flat, uniform image) must not crash —
        falls back to the full image bounds."""
        source = _solid_bytes(size=(150, 150))
        output, _ct, width, height = apply_operations(
            source, [ImageEditOperation(type="REMOVE_EMPTY_SPACE")]
        )
        assert (width, height) == (150, 150)

    def test_auto_center_keeps_canvas_size_and_centers_content(self):
        source = self._off_center_product_bytes(size=(300, 300))
        output, _ct, width, height = apply_operations(
            source, [ImageEditOperation(type="AUTO_CENTER")]
        )
        assert (width, height) == (300, 300)  # canvas size unchanged
        arr = np.array(_decode(output).convert("RGB"))
        # The dark square should no longer be tucked in the top-left corner —
        # that corner should now read close to the background color.
        assert arr[5, 5].mean() > 200  # near-white corner
        # And the true center should now show at least some non-background
        # (foreground) pixels somewhere in a small window around it.
        cx, cy = width // 2, height // 2
        window = arr[cy - 20:cy + 20, cx - 20:cx + 20]
        assert window.mean() < 240  # not purely background-white anymore

    def test_auto_scale_fills_target_ratio_of_shorter_dimension(self):
        source = self._off_center_product_bytes(size=(300, 300))
        output, _ct, width, height = apply_operations(
            source, [ImageEditOperation(type="AUTO_SCALE", fill_ratio=0.5)]
        )
        assert (width, height) == (300, 300)
        arr = np.array(_decode(output).convert("L"))
        dark_pixel_count = int((arr < 100).sum())
        # Original foreground square was 60x60 = 3600px on a 300x300 canvas;
        # scaling it to fill ~50% of the shorter dimension (150px) should
        # produce a visibly larger dark region than the untouched original.
        assert dark_pixel_count > 3600

    def test_auto_scale_preserves_transparency_when_source_has_alpha(self):
        source = _product_on_backdrop_bytes(size=(160, 160))
        output, content_type, _w, _h = apply_operations(
            source,
            [
                ImageEditOperation(type="BACKGROUND_REPLACE", mode="TRANSPARENT"),
                ImageEditOperation(type="AUTO_SCALE", fill_ratio=0.6),
            ],
        )
        assert content_type == "image/png"
        assert _decode(output).mode == "RGBA"
