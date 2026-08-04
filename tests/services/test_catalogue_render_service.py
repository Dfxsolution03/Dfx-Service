"""
DFX Solution Service Tests — Catalogue Render Service
(Jewellery Catalogue & Marketing Studio, Phase B)
=========================================================

Pure unit tests, no DB — render_canvas()/build_pdf_from_images() are
domain-agnostic (a CanvasDocument + resolved image bytes in, final image/PDF
bytes out), tested in isolation from CatalogueService, storage, and the API
layer. Mirrors test_image_processing_service.py's own house style from
Phase A.
"""

import io

import pytest
from PIL import Image

from app.schemas.catalogue import CanvasDocument
from app.services.catalogue_asset_library import TEMPLATE_PRESETS, BADGE_PRESETS, OVERLAY_KEYS, resolve_font
from app.services.catalogue_render_service import render_canvas, build_pdf_from_images


def _product_photo_bytes(size=(400, 300), color=(120, 90, 40)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color=color).save(buffer, format="JPEG")
    return buffer.getvalue()


def _layer(**kwargs) -> dict:
    base = {"id": "layer_1", "type": "SHAPE", "x": 0, "y": 0, "width": 100, "height": 100, "z_index": 0}
    base.update(kwargs)
    return base


class TestRenderQuality:
    """Product Studio redesign — Quality is a real JPEG-quality parameter,
    not a cosmetic label."""

    def test_lower_quality_produces_smaller_file_for_the_same_canvas(self):
        canvas = CanvasDocument(
            canvas_width=400, canvas_height=400,
            layers=[_layer(id="s", type="SHAPE", shape_kind="RECTANGLE", color="#7A0C2E", width=400, height=400)],
        )
        low, _ct, _w, _h = render_canvas(canvas, {}, quality=40)
        high, _ct2, _w2, _h2 = render_canvas(canvas, {}, quality=100)
        assert len(low) < len(high)

    def test_default_quality_matches_previous_hardcoded_value(self):
        canvas = CanvasDocument(canvas_width=100, canvas_height=100, layers=[])
        default_call, _ct, _w, _h = render_canvas(canvas, {})
        explicit_92, _ct2, _w2, _h2 = render_canvas(canvas, {}, quality=92)
        assert default_call == explicit_92

    def test_quality_is_clamped_to_valid_jpeg_range(self):
        canvas = CanvasDocument(canvas_width=50, canvas_height=50, layers=[])
        # Out-of-range inputs must not crash Pillow's JPEG encoder.
        render_canvas(canvas, {}, quality=0)
        render_canvas(canvas, {}, quality=500)


class TestRenderCanvasBasics:
    def test_renders_flat_opaque_jpeg_at_declared_size(self):
        canvas = CanvasDocument(canvas_width=300, canvas_height=200, layers=[])
        output, content_type, w, h = render_canvas(canvas, {})
        assert content_type == "image/jpeg"
        assert (w, h) == (300, 200)
        decoded = Image.open(io.BytesIO(output))
        assert decoded.mode == "RGB"  # always flattened/opaque, never RGBA
        assert decoded.size == (300, 200)

    def test_hidden_layer_is_not_drawn(self):
        canvas = CanvasDocument(
            canvas_width=100, canvas_height=100,
            layers=[_layer(shape_kind="RECTANGLE", color="#FF0000", width=100, height=100, visible=False)],
        )
        output, _ct, _w, _h = render_canvas(canvas, {})
        pixel = Image.open(io.BytesIO(output)).convert("RGB").getpixel((50, 50))
        assert pixel == (255, 255, 255)  # base canvas stays white — nothing drawn

    def test_z_index_controls_stacking_order(self):
        canvas = CanvasDocument(
            canvas_width=100, canvas_height=100,
            layers=[
                _layer(id="back", shape_kind="RECTANGLE", color="#0000FF", width=100, height=100, z_index=0),
                _layer(id="front", shape_kind="RECTANGLE", color="#FF0000", width=100, height=100, z_index=10),
            ],
        )
        output, _ct, _w, _h = render_canvas(canvas, {})
        pixel = Image.open(io.BytesIO(output)).convert("RGB").getpixel((50, 50))
        assert pixel[0] > pixel[2]  # red (higher z_index) drawn on top of blue

    def test_unsupported_layer_type_raises(self):
        canvas = CanvasDocument(canvas_width=50, canvas_height=50, layers=[])
        # Bypass Pydantic's Literal validation to exercise the renderer's own
        # defensive dispatch check directly.
        bad_layer = canvas.layers  # placeholder, real check below
        from app.schemas.catalogue import CanvasLayer
        layer = CanvasLayer.model_construct(
            id="x", type="NOT_A_REAL_TYPE", x=0, y=0, width=10, height=10, rotation=0,
            scale=1.0, opacity=1.0, visible=True, locked=False, z_index=0, props={},
        )
        canvas = canvas.model_copy(update={"layers": [layer]})
        with pytest.raises(ValueError):
            render_canvas(canvas, {})


class TestProductLayer:
    def test_product_layer_cover_fits_referenced_image(self):
        photo = _product_photo_bytes(size=(400, 300))
        canvas = CanvasDocument(
            canvas_width=200, canvas_height=200,
            layers=[_layer(id="p", type="PRODUCT", width=200, height=200, image_id="img1")],
        )
        output, _ct, w, h = render_canvas(canvas, {"img1": photo})
        assert (w, h) == (200, 200)
        pixel = Image.open(io.BytesIO(output)).convert("RGB").getpixel((100, 100))
        assert pixel != (255, 255, 255)  # the photo actually got drawn, not left blank

    def test_missing_image_reference_renders_placeholder_not_crash(self):
        canvas = CanvasDocument(
            canvas_width=100, canvas_height=100,
            layers=[_layer(id="p", type="PRODUCT", width=100, height=100, image_id="does_not_exist")],
        )
        output, _ct, _w, _h = render_canvas(canvas, {})  # empty image dict
        assert Image.open(io.BytesIO(output)).size == (100, 100)  # doesn't raise


class TestTextLayer:
    def test_text_layer_draws_non_blank_pixels(self):
        canvas = CanvasDocument(
            canvas_width=300, canvas_height=100,
            layers=[_layer(
                id="t", type="TEXT", width=300, height=100,
                text="DFX", font_family="POPPINS", font_weight="BOLD", font_size=48,
                text_align="CENTER", color="#000000",
            )],
        )
        output, _ct, _w, _h = render_canvas(canvas, {})
        arr_has_dark_pixel = any(
            sum(Image.open(io.BytesIO(output)).convert("RGB").getpixel((x, 50))) < 300
            for x in range(0, 300, 5)
        )
        assert arr_has_dark_pixel

    def test_empty_text_does_not_crash(self):
        canvas = CanvasDocument(
            canvas_width=100, canvas_height=100,
            layers=[_layer(id="t", type="TEXT", width=100, height=50, text="")],
        )
        output, _ct, _w, _h = render_canvas(canvas, {})
        assert Image.open(io.BytesIO(output)).size == (100, 100)


class TestBadgeAndOverlayAndQR:
    @pytest.mark.parametrize("badge_key", list(BADGE_PRESETS.keys()))
    def test_every_badge_preset_renders(self, badge_key):
        canvas = CanvasDocument(
            canvas_width=200, canvas_height=100,
            layers=[_layer(id="b", type="BADGE", width=180, height=70, badge_key=badge_key)],
        )
        output, _ct, _w, _h = render_canvas(canvas, {})
        assert Image.open(io.BytesIO(output)).size == (200, 100)

    @pytest.mark.parametrize("overlay_key", OVERLAY_KEYS)
    def test_every_overlay_preset_renders(self, overlay_key):
        canvas = CanvasDocument(
            canvas_width=300, canvas_height=300,
            layers=[_layer(id="o", type="OVERLAY", width=300, height=300, overlay_key=overlay_key)],
        )
        output, _ct, _w, _h = render_canvas(canvas, {})
        assert Image.open(io.BytesIO(output)).size == (300, 300)

    def test_sparkles_are_deterministic_for_the_same_layer_id(self):
        canvas = CanvasDocument(
            canvas_width=200, canvas_height=200,
            layers=[_layer(id="fixed_id", type="OVERLAY", width=200, height=200, overlay_key="SPARKLES")],
        )
        output_a, _ct, _w, _h = render_canvas(canvas, {})
        output_b, _ct2, _w2, _h2 = render_canvas(canvas, {})
        assert output_a == output_b  # same layer id -> identical sparkle positions every render

    def test_qr_layer_renders_scannable_looking_pattern(self):
        canvas = CanvasDocument(
            canvas_width=150, canvas_height=150,
            layers=[_layer(id="qr", type="QR", width=150, height=150, qr_payload="https://example.com/p/123")],
        )
        output, _ct, _w, _h = render_canvas(canvas, {})
        img = Image.open(io.BytesIO(output)).convert("L")
        # A QR code has both near-black and near-white regions — a blank
        # render (e.g. an empty payload bug) would fail this.
        pixels = list(img.getdata())
        assert min(pixels) < 60 and max(pixels) > 200

    def test_empty_qr_payload_does_not_crash(self):
        canvas = CanvasDocument(
            canvas_width=100, canvas_height=100,
            layers=[_layer(id="qr", type="QR", width=100, height=100, qr_payload="")],
        )
        output, _ct, _w, _h = render_canvas(canvas, {})
        assert Image.open(io.BytesIO(output)).size == (100, 100)


class TestTransformPlacement:
    def test_opacity_blends_toward_background(self):
        canvas_opaque = CanvasDocument(
            canvas_width=100, canvas_height=100,
            layers=[_layer(id="s", type="SHAPE", shape_kind="RECTANGLE", color="#FF0000", width=100, height=100, opacity=1.0)],
        )
        canvas_transparent = canvas_opaque.model_copy(deep=True)
        canvas_transparent.layers[0].opacity = 0.3

        opaque_pixel = Image.open(io.BytesIO(render_canvas(canvas_opaque, {})[0])).convert("RGB").getpixel((50, 50))
        faded_pixel = Image.open(io.BytesIO(render_canvas(canvas_transparent, {})[0])).convert("RGB").getpixel((50, 50))
        assert faded_pixel[0] < opaque_pixel[0]  # faded red is lighter/less saturated than full-opacity red
        assert faded_pixel[1] > opaque_pixel[1]  # more of the white background shows through

    def test_scale_grows_effective_size(self):
        canvas_small = CanvasDocument(
            canvas_width=200, canvas_height=200,
            layers=[_layer(id="s", type="SHAPE", shape_kind="CIRCLE", color="#FF0000", x=50, y=50, width=50, height=50, scale=1.0)],
        )
        canvas_big = canvas_small.model_copy(deep=True)
        canvas_big.layers[0].scale = 2.0

        def _red_pixel_count(canvas):
            img = Image.open(io.BytesIO(render_canvas(canvas, {})[0])).convert("RGB")
            return sum(1 for p in img.getdata() if p[0] > 200 and p[1] < 100)

        assert _red_pixel_count(canvas_big) > _red_pixel_count(canvas_small)


class TestTemplatePresetsRenderCleanly:
    @pytest.mark.parametrize("template_key", list(TEMPLATE_PRESETS.keys()))
    def test_every_template_preset_is_a_valid_canvas_document(self, template_key):
        canvas = CanvasDocument(**TEMPLATE_PRESETS[template_key])
        output, content_type, w, h = render_canvas(canvas, {})
        assert content_type == "image/jpeg"
        assert (w, h) == (int(canvas.canvas_width), int(canvas.canvas_height))


class TestFontResolution:
    def test_resolves_all_three_bundled_families(self):
        for family in ["PLAYFAIR_DISPLAY", "POPPINS", "GREAT_VIBES"]:
            font = resolve_font(family, "BOLD", 32)
            assert font is not None

    def test_unknown_family_falls_back_instead_of_raising(self):
        font = resolve_font("SOME_FUTURE_FONT_NOT_BUNDLED_YET", "REGULAR", 24)
        assert font is not None


class TestCataloguePdf:
    def test_builds_valid_multi_page_pdf(self):
        page1 = (_product_photo_bytes(size=(300, 300)), 300, 300)
        page2 = (_product_photo_bytes(size=(300, 300), color=(10, 10, 10)), 300, 300)
        pdf_bytes = build_pdf_from_images([page1, page2])
        assert pdf_bytes.startswith(b"%PDF")
        # A crude but reliable page-count check: reportlab emits one "/Type
        # /Page" object dict per page it wrote (distinct from "/Pages").
        assert pdf_bytes.count(b"/Type /Page") - pdf_bytes.count(b"/Type /Pages") == 2

    def test_single_page_pdf(self):
        pdf_bytes = build_pdf_from_images([(_product_photo_bytes(), 400, 300)])
        assert pdf_bytes.startswith(b"%PDF")
