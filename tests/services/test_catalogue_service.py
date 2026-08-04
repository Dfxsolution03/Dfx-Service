"""
DFX Solution Service Tests — CatalogueService (Module 20)
==========================================================
"""

import io
import pytest
from fastapi import UploadFile
from starlette.datastructures import Headers

from app.services.catalogue_service import CatalogueService
from app.schemas.catalogue import (
    ProductCreateRequest,
    ProductUpdateRequest,
    ImageReorderRequest,
    EnhancementRequest,
    ImageEditRequest,
    ImageEditOperation,
    CanvasDocument,
    CatalogueDesignSaveRequest,
    CatalogueDesignCloneRequest,
    RenderPreviewRequest,
    ExportDesignRequest,
    BatchRenderRequest,
    CataloguePdfRequest,
)
from app.exceptions.base import ForbiddenException, ValidationException, ResourceNotFoundException


def _fake_upload(content: bytes = b"\xff\xd8\xff\xe0fakejpegbytes", content_type: str = "image/jpeg", filename: str = "test.jpg") -> UploadFile:
    return UploadFile(
        file=io.BytesIO(content),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )


def _real_jpeg_upload(filename: str = "real.jpg") -> UploadFile:
    """Module 21 — a genuinely decodable JPEG, needed to exercise real
    thumbnail generation (Module 20's _fake_upload() bytes aren't valid
    image data, so Pillow can't decode them — see
    CatalogueService._generate_thumbnail_bytes' best-effort try/except)."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (800, 600), color=(120, 90, 40)).save(buffer, format="JPEG")
    return UploadFile(
        file=io.BytesIO(buffer.getvalue()),
        filename=filename,
        headers=Headers({"content-type": "image/jpeg"}),
    )


class TestCreateProduct:
    async def test_create_product_success(self, db_session, admin_user):
        req = ProductCreateRequest(name="Bridal Set", description=None, category="Bridal", sku=None)
        product = await CatalogueService.create_product(db_session, admin_user, req)
        assert product.name == "Bridal Set"
        assert product.is_active is True
        assert product.image_count == 0

    async def test_create_product_requires_tenant(self, db_session, superadmin_user):
        req = ProductCreateRequest(name="No Tenant Product")
        with pytest.raises(ForbiddenException):
            await CatalogueService.create_product(db_session, superadmin_user, req)

    async def test_create_product_with_commercial_fields(self, db_session, admin_user):
        """Product Studio redesign — purity/price/weight_grams/tags are real,
        persisted columns now, not display-only frontend state."""
        req = ProductCreateRequest(
            name="22K Gold Necklace",
            purity="22K",
            price=125000.50,
            weight_grams=18.75,
            tags=["bridal", "gold", "necklace"],
        )
        product = await CatalogueService.create_product(db_session, admin_user, req)
        assert product.purity == "22K"
        assert product.price == 125000.50
        assert product.weight_grams == 18.75
        assert product.tags == ["bridal", "gold", "necklace"]

        # Confirm it round-trips through a fresh fetch (not just the
        # in-memory response object returned by create).
        fetched = await CatalogueService.get_product_by_id(db_session, admin_user, product.id)
        assert fetched.purity == "22K"
        assert fetched.tags == ["bridal", "gold", "necklace"]

    async def test_create_product_without_commercial_fields_defaults_sensibly(self, db_session, admin_user):
        product = await CatalogueService.create_product(
            db_session, admin_user, ProductCreateRequest(name="No Extras")
        )
        assert product.purity is None
        assert product.price is None
        assert product.weight_grams is None
        assert product.tags == []


class TestUpdateAndDeactivateProduct:
    async def test_update_product_fields(self, db_session, admin_user):
        product = await CatalogueService.create_product(
            db_session, admin_user, ProductCreateRequest(name="Original Name")
        )
        updated = await CatalogueService.update_product(
            db_session, admin_user, product.id, ProductUpdateRequest(name="Renamed")
        )
        assert updated.name == "Renamed"

    async def test_update_commercial_fields_and_tags(self, db_session, admin_user):
        product = await CatalogueService.create_product(
            db_session, admin_user, ProductCreateRequest(name="Bangle", tags=["old-tag"])
        )
        updated = await CatalogueService.update_product(
            db_session, admin_user, product.id,
            ProductUpdateRequest(purity="916", price=54000.0, weight_grams=12.0, tags=["new-tag", "trending"]),
        )
        assert updated.purity == "916"
        assert updated.price == 54000.0
        assert updated.tags == ["new-tag", "trending"]

    async def test_update_with_empty_tags_list_clears_tags(self, db_session, admin_user):
        product = await CatalogueService.create_product(
            db_session, admin_user, ProductCreateRequest(name="Ring", tags=["a", "b"])
        )
        updated = await CatalogueService.update_product(
            db_session, admin_user, product.id, ProductUpdateRequest(tags=[])
        )
        assert updated.tags == []

    async def test_update_omitting_tags_leaves_them_unchanged(self, db_session, admin_user):
        product = await CatalogueService.create_product(
            db_session, admin_user, ProductCreateRequest(name="Earrings", tags=["keep-me"])
        )
        updated = await CatalogueService.update_product(
            db_session, admin_user, product.id, ProductUpdateRequest(name="Earrings Renamed")
        )
        assert updated.tags == ["keep-me"]

    async def test_update_nonexistent_product_raises_404(self, db_session, admin_user):
        with pytest.raises(ResourceNotFoundException):
            await CatalogueService.update_product(
                db_session, admin_user, "prd_does_not_exist", ProductUpdateRequest(name="XX")
            )

    async def test_deactivate_product_sets_inactive(self, db_session, admin_user):
        product = await CatalogueService.create_product(
            db_session, admin_user, ProductCreateRequest(name="To Deactivate")
        )
        await CatalogueService.deactivate_product(db_session, admin_user, product.id)
        fetched = await CatalogueService.get_product_by_id(db_session, admin_user, product.id)
        assert fetched.is_active is False


class TestUploadImage:
    async def test_upload_creates_original_and_auto_sets_primary(self, db_session, admin_user):
        product = await CatalogueService.create_product(
            db_session, admin_user, ProductCreateRequest(name="Ring")
        )
        image = await CatalogueService.upload_image(
            db_session, admin_user, product.id, _fake_upload()
        )
        assert image.variant_type == "ORIGINAL"
        assert image.is_primary is True  # first image for the product

        fetched = await CatalogueService.get_product_by_id(db_session, admin_user, product.id)
        assert fetched.image_count == 1
        assert fetched.primary_image_url == image.url

    async def test_upload_persists_shot_type(self, db_session, admin_user):
        """Product Studio redesign — Step 2's Front/Back/Side/Top/45°/
        Lifestyle/Macro tagging must actually survive a reload, not just
        exist as ephemeral frontend state."""
        product = await CatalogueService.create_product(
            db_session, admin_user, ProductCreateRequest(name="Tagged Upload Test")
        )
        image = await CatalogueService.upload_image(
            db_session, admin_user, product.id, _fake_upload(), shot_type="FRONT"
        )
        assert image.shot_type == "FRONT"

        fetched = await CatalogueService.get_product_by_id(db_session, admin_user, product.id)
        original = next(i for i in fetched.images if i.variant_type == "ORIGINAL")
        assert original.shot_type == "FRONT"

    async def test_upload_without_shot_type_is_none(self, db_session, admin_user):
        product = await CatalogueService.create_product(
            db_session, admin_user, ProductCreateRequest(name="Untagged Upload Test")
        )
        image = await CatalogueService.upload_image(db_session, admin_user, product.id, _fake_upload())
        assert image.shot_type is None

    async def test_second_upload_is_not_auto_primary(self, db_session, admin_user):
        product = await CatalogueService.create_product(
            db_session, admin_user, ProductCreateRequest(name="Ring 2")
        )
        first = await CatalogueService.upload_image(db_session, admin_user, product.id, _fake_upload())
        second = await CatalogueService.upload_image(db_session, admin_user, product.id, _fake_upload())
        assert first.is_primary is True
        assert second.is_primary is False

    async def test_upload_rejects_unsupported_content_type(self, db_session, admin_user):
        product = await CatalogueService.create_product(
            db_session, admin_user, ProductCreateRequest(name="Bad Upload")
        )
        bad_file = _fake_upload(content_type="application/pdf", filename="not-an-image.pdf")
        with pytest.raises(ValidationException):
            await CatalogueService.upload_image(db_session, admin_user, product.id, bad_file)

    async def test_upload_rejects_empty_file(self, db_session, admin_user):
        product = await CatalogueService.create_product(
            db_session, admin_user, ProductCreateRequest(name="Empty Upload")
        )
        empty_file = _fake_upload(content=b"")
        with pytest.raises(ValidationException):
            await CatalogueService.upload_image(db_session, admin_user, product.id, empty_file)


class TestSetPrimaryAndReorder:
    async def test_set_primary_switches_flag(self, db_session, admin_user):
        product = await CatalogueService.create_product(
            db_session, admin_user, ProductCreateRequest(name="Bangle")
        )
        first = await CatalogueService.upload_image(db_session, admin_user, product.id, _fake_upload())
        second = await CatalogueService.upload_image(db_session, admin_user, product.id, _fake_upload())

        await CatalogueService.set_primary_image(db_session, admin_user, product.id, second.id)

        fetched = await CatalogueService.get_product_by_id(db_session, admin_user, product.id)
        primary_images = [i for i in fetched.images if i.is_primary]
        assert len(primary_images) == 1
        assert primary_images[0].id == second.id

    async def test_reorder_updates_display_order(self, db_session, admin_user):
        product = await CatalogueService.create_product(
            db_session, admin_user, ProductCreateRequest(name="Earrings")
        )
        first = await CatalogueService.upload_image(db_session, admin_user, product.id, _fake_upload())
        second = await CatalogueService.upload_image(db_session, admin_user, product.id, _fake_upload())

        await CatalogueService.reorder_images(
            db_session, admin_user, product.id, ImageReorderRequest(image_ids=[second.id, first.id])
        )

        fetched = await CatalogueService.get_product_by_id(db_session, admin_user, product.id)
        originals = sorted(
            (i for i in fetched.images if i.variant_type == "ORIGINAL"), key=lambda i: i.display_order
        )
        assert originals[0].id == second.id
        assert originals[1].id == first.id

    async def test_reorder_rejects_mismatched_id_set(self, db_session, admin_user):
        product = await CatalogueService.create_product(
            db_session, admin_user, ProductCreateRequest(name="Pendant")
        )
        await CatalogueService.upload_image(db_session, admin_user, product.id, _fake_upload())
        with pytest.raises(ValidationException):
            await CatalogueService.reorder_images(
                db_session, admin_user, product.id, ImageReorderRequest(image_ids=["img_nonexistent"])
            )


class TestDeleteImage:
    async def test_delete_promotes_next_original_to_primary(self, db_session, admin_user):
        product = await CatalogueService.create_product(
            db_session, admin_user, ProductCreateRequest(name="Chain")
        )
        first = await CatalogueService.upload_image(db_session, admin_user, product.id, _fake_upload())
        second = await CatalogueService.upload_image(db_session, admin_user, product.id, _fake_upload())

        await CatalogueService.delete_image(db_session, admin_user, product.id, first.id)

        fetched = await CatalogueService.get_product_by_id(db_session, admin_user, product.id)
        assert len(fetched.images) == 1
        assert fetched.images[0].id == second.id
        assert fetched.images[0].is_primary is True


class TestEnhanceImage:
    async def test_enhance_raises_clear_not_configured_error(self, db_session, admin_user):
        product = await CatalogueService.create_product(
            db_session, admin_user, ProductCreateRequest(name="Necklace")
        )
        image = await CatalogueService.upload_image(db_session, admin_user, product.id, _fake_upload())

        with pytest.raises(ValidationException) as exc_info:
            await CatalogueService.enhance_image(
                db_session,
                admin_user,
                product.id,
                image.id,
                EnhancementRequest(enhancement_type="REMOVE_BACKGROUND"),
            )
        assert "not yet configured" in str(exc_info.value.message).lower()


class TestThumbnailGeneration:
    """Module 21, Phase 8 — real Pillow-based thumbnails, verified with a
    genuinely decodable image (Module 20's fake bytes can't exercise this
    path at all — see _real_jpeg_upload's docstring)."""

    async def test_upload_creates_a_real_thumbnail_variant(self, db_session, admin_user):
        product = await CatalogueService.create_product(
            db_session, admin_user, ProductCreateRequest(name="Thumbnail Test")
        )
        await CatalogueService.upload_image(db_session, admin_user, product.id, _real_jpeg_upload())

        fetched = await CatalogueService.get_product_by_id(db_session, admin_user, product.id)
        assert fetched.image_count == 2  # ORIGINAL + THUMBNAIL
        thumbnails = [i for i in fetched.images if i.variant_type == "THUMBNAIL"]
        assert len(thumbnails) == 1
        originals = [i for i in fetched.images if i.variant_type == "ORIGINAL"]
        assert thumbnails[0].source_image_id == originals[0].id

    async def test_thumbnail_is_actually_smaller_than_original(self, db_session, admin_user):
        product = await CatalogueService.create_product(
            db_session, admin_user, ProductCreateRequest(name="Size Check")
        )
        await CatalogueService.upload_image(db_session, admin_user, product.id, _real_jpeg_upload())
        fetched = await CatalogueService.get_product_by_id(db_session, admin_user, product.id)

        original = next(i for i in fetched.images if i.variant_type == "ORIGINAL")
        thumbnail = next(i for i in fetched.images if i.variant_type == "THUMBNAIL")
        assert thumbnail.file_size_bytes < original.file_size_bytes

    async def test_invalid_image_bytes_upload_still_succeeds_without_thumbnail(self, db_session, admin_user):
        """The original upload must never fail just because a best-effort
        thumbnail couldn't be generated."""
        product = await CatalogueService.create_product(
            db_session, admin_user, ProductCreateRequest(name="No Thumbnail")
        )
        await CatalogueService.upload_image(db_session, admin_user, product.id, _fake_upload())
        fetched = await CatalogueService.get_product_by_id(db_session, admin_user, product.id)
        assert fetched.image_count == 1  # ORIGINAL only — thumbnail generation silently no-opped


class TestPipelineStatus:
    async def test_pipeline_status_shows_only_original_completed_for_fresh_upload(self, db_session, admin_user):
        product = await CatalogueService.create_product(
            db_session, admin_user, ProductCreateRequest(name="Pipeline Test")
        )
        image = await CatalogueService.upload_image(db_session, admin_user, product.id, _fake_upload())

        status = await CatalogueService.get_pipeline_status(db_session, admin_user, product.id, image.id)
        assert status.source_image_id == image.id
        assert status.ai_provider_configured is False
        stages_by_type = {s.variant_type: s.completed for s in status.stages}
        assert stages_by_type["ORIGINAL"] is True
        assert stages_by_type["BACKGROUND_REMOVED"] is False
        assert stages_by_type["ENHANCED"] is False
        assert stages_by_type["LUXURY_LIGHTING"] is False
        assert stages_by_type["FINAL_CATALOGUE"] is False

    async def test_pipeline_status_rejects_non_original_image(self, db_session, admin_user):
        product = await CatalogueService.create_product(
            db_session, admin_user, ProductCreateRequest(name="Pipeline Reject Test")
        )
        await CatalogueService.upload_image(db_session, admin_user, product.id, _real_jpeg_upload())
        fetched = await CatalogueService.get_product_by_id(db_session, admin_user, product.id)
        thumbnail = next(i for i in fetched.images if i.variant_type == "THUMBNAIL")

        with pytest.raises(ValidationException):
            await CatalogueService.get_pipeline_status(db_session, admin_user, product.id, thumbnail.id)

    async def test_pipeline_status_nonexistent_image_raises_404(self, db_session, admin_user):
        product = await CatalogueService.create_product(
            db_session, admin_user, ProductCreateRequest(name="Pipeline 404 Test")
        )
        with pytest.raises(ResourceNotFoundException):
            await CatalogueService.get_pipeline_status(db_session, admin_user, product.id, "img_does_not_exist")


class TestAIProviderStatus:
    def test_reports_stub_and_not_configured(self):
        status = CatalogueService.get_ai_provider_status()
        assert status.provider == "Stub"
        assert status.configured is False


class TestImageEditor:
    """Jewellery Catalogue & Marketing Studio, Phase A — real, local
    Pillow/OpenCV editing. Session model: Original -> Editing Session
    (ephemeral) -> Preview (never persisted) -> Save (persisted exactly
    once, as a new EDITED row)."""

    async def _product_with_real_image(self, db_session, admin_user, name="Edit Test"):
        product = await CatalogueService.create_product(
            db_session, admin_user, ProductCreateRequest(name=name)
        )
        image = await CatalogueService.upload_image(
            db_session, admin_user, product.id, _real_jpeg_upload()
        )
        return product, image

    async def test_preview_does_not_persist_anything(self, db_session, admin_user):
        product, image = await self._product_with_real_image(db_session, admin_user)
        before = await CatalogueService.get_product_by_id(db_session, admin_user, product.id)

        result = await CatalogueService.preview_edit_image(
            db_session,
            admin_user,
            product.id,
            image.id,
            ImageEditRequest(operations=[ImageEditOperation(type="BRIGHTNESS", factor=1.2)]),
        )
        assert result.content_base64
        assert result.content_type in ("image/jpeg", "image/png")

        after = await CatalogueService.get_product_by_id(db_session, admin_user, product.id)
        assert after.image_count == before.image_count  # no new row from preview

    async def test_save_creates_new_edited_variant_with_source_lineage(self, db_session, admin_user):
        product, image = await self._product_with_real_image(db_session, admin_user)
        before = await CatalogueService.get_product_by_id(db_session, admin_user, product.id)

        edited = await CatalogueService.save_edit_image(
            db_session,
            admin_user,
            product.id,
            image.id,
            ImageEditRequest(
                operations=[
                    ImageEditOperation(type="CROP", x=0, y=0, width=400, height=300),
                    ImageEditOperation(type="CONTRAST", factor=1.1),
                ]
            ),
        )
        assert edited.variant_type == "EDITED"
        assert edited.source_image_id == image.id
        assert edited.is_primary is False  # never auto-primary, matching other derived variants

        after = await CatalogueService.get_product_by_id(db_session, admin_user, product.id)
        assert after.image_count == before.image_count + 1

    async def test_save_never_overwrites_the_source_image(self, db_session, admin_user):
        product, image = await self._product_with_real_image(db_session, admin_user)
        await CatalogueService.save_edit_image(
            db_session,
            admin_user,
            product.id,
            image.id,
            ImageEditRequest(operations=[ImageEditOperation(type="BRIGHTNESS", factor=0.9)]),
        )
        fetched = await CatalogueService.get_product_by_id(db_session, admin_user, product.id)
        original_still_present = next(
            (i for i in fetched.images if i.id == image.id and i.variant_type == "ORIGINAL"), None
        )
        assert original_still_present is not None

    async def test_edit_nonexistent_image_raises_404(self, db_session, admin_user):
        product = await CatalogueService.create_product(
            db_session, admin_user, ProductCreateRequest(name="404 Edit Test")
        )
        with pytest.raises(ResourceNotFoundException):
            await CatalogueService.preview_edit_image(
                db_session,
                admin_user,
                product.id,
                "img_does_not_exist",
                ImageEditRequest(operations=[ImageEditOperation(type="BRIGHTNESS", factor=1.0)]),
            )

    async def test_edit_image_belonging_to_different_product_raises_404(self, db_session, admin_user):
        _product_a, image_a = await self._product_with_real_image(db_session, admin_user, name="Product A")
        product_b = await CatalogueService.create_product(
            db_session, admin_user, ProductCreateRequest(name="Product B")
        )
        with pytest.raises(ResourceNotFoundException):
            await CatalogueService.preview_edit_image(
                db_session,
                admin_user,
                product_b.id,
                image_a.id,
                ImageEditRequest(operations=[ImageEditOperation(type="BRIGHTNESS", factor=1.0)]),
            )

    async def test_invalid_operation_params_raise_validation_exception(self, db_session, admin_user):
        product, image = await self._product_with_real_image(db_session, admin_user)
        with pytest.raises(ValidationException):
            await CatalogueService.preview_edit_image(
                db_session,
                admin_user,
                product.id,
                image.id,
                # ROTATE with no degrees — image_processing_service raises
                # ValueError, which the service layer must translate to a
                # ValidationException (400), not let bubble up raw.
                ImageEditRequest(operations=[ImageEditOperation(type="ROTATE")]),
            )


def _text_only_canvas(w=400, h=300) -> CanvasDocument:
    """A canvas that needs no image references at all — the simplest valid
    design, used everywhere a test doesn't care about the Product layer."""
    return CanvasDocument(
        canvas_width=w, canvas_height=h,
        layers=[
            {
                "id": "bg", "type": "BACKGROUND", "x": 0, "y": 0, "width": w, "height": h,
                "z_index": 0, "color": "#FFFFFF",
            },
            {
                "id": "txt", "type": "TEXT", "x": 20, "y": 20, "width": w - 40, "height": 60,
                "z_index": 10, "text": "Test Design", "font_family": "POPPINS", "font_size": 28,
            },
        ],
    )


def _product_layer_canvas(w=400, h=300) -> CanvasDocument:
    """A canvas with an unresolved PRODUCT layer (image_id=None) — exactly
    the shape a template preset has, to exercise per-product resolution."""
    return CanvasDocument(
        canvas_width=w, canvas_height=h,
        layers=[
            {"id": "bg", "type": "BACKGROUND", "x": 0, "y": 0, "width": w, "height": h, "z_index": 0, "color": "#FFFFFF"},
            {"id": "prod", "type": "PRODUCT", "x": 20, "y": 20, "width": w - 40, "height": h - 40, "z_index": 10, "image_id": None},
        ],
    )


class TestCatalogueDesignVersioning:
    """Phase B — CatalogueDesign is insert-only: every Save creates a new
    immutable version. Restore/Duplicate both clone an existing version
    rather than mutating anything."""

    async def _make_product(self, db_session, admin_user, name="Design Test Product"):
        return await CatalogueService.create_product(db_session, admin_user, ProductCreateRequest(name=name))

    async def test_first_save_is_version_1(self, db_session, admin_user):
        product = await self._make_product(db_session, admin_user)
        design = await CatalogueService.save_design(
            db_session, admin_user, product.id, CatalogueDesignSaveRequest(canvas=_text_only_canvas(), name="Draft 1")
        )
        assert design.version == 1
        assert design.source_design_id is None
        assert design.canvas.layers[1].text == "Test Design"  # nothing flattened — the layer is still editable JSON

    async def test_second_save_is_version_2_and_first_still_exists(self, db_session, admin_user):
        product = await self._make_product(db_session, admin_user)
        await CatalogueService.save_design(db_session, admin_user, product.id, CatalogueDesignSaveRequest(canvas=_text_only_canvas()))
        second = await CatalogueService.save_design(db_session, admin_user, product.id, CatalogueDesignSaveRequest(canvas=_text_only_canvas()))
        assert second.version == 2

        history = await CatalogueService.get_designs(db_session, admin_user, product.id)
        assert [d.version for d in history] == [2, 1]  # newest first

    async def test_get_design_by_id(self, db_session, admin_user):
        product = await self._make_product(db_session, admin_user)
        saved = await CatalogueService.save_design(
            db_session, admin_user, product.id, CatalogueDesignSaveRequest(canvas=_text_only_canvas(), name="Named Design")
        )
        fetched = await CatalogueService.get_design(db_session, admin_user, product.id, saved.id)
        assert fetched.name == "Named Design"

    async def test_restore_creates_new_version_keeping_original_name(self, db_session, admin_user):
        product = await self._make_product(db_session, admin_user)
        v1 = await CatalogueService.save_design(
            db_session, admin_user, product.id, CatalogueDesignSaveRequest(canvas=_text_only_canvas(), name="Original")
        )
        await CatalogueService.save_design(db_session, admin_user, product.id, CatalogueDesignSaveRequest(canvas=_text_only_canvas(), name="v2"))

        restored = await CatalogueService.restore_design(
            db_session, admin_user, product.id, v1.id, CatalogueDesignCloneRequest()
        )
        assert restored.version == 3  # newest version, history is never rewritten
        assert restored.source_design_id == v1.id
        assert restored.name == "Original"

        history = await CatalogueService.get_designs(db_session, admin_user, product.id)
        assert len(history) == 3  # v1 was never deleted or overwritten

    async def test_duplicate_creates_new_version_with_copy_suffix(self, db_session, admin_user):
        product = await self._make_product(db_session, admin_user)
        v1 = await CatalogueService.save_design(
            db_session, admin_user, product.id, CatalogueDesignSaveRequest(canvas=_text_only_canvas(), name="Base")
        )
        duplicate = await CatalogueService.duplicate_design(
            db_session, admin_user, product.id, v1.id, CatalogueDesignCloneRequest()
        )
        assert duplicate.name == "Base (Copy)"
        assert duplicate.source_design_id == v1.id
        assert duplicate.canvas.layers == v1.canvas.layers  # cloned verbatim

    async def test_nonexistent_design_raises_404(self, db_session, admin_user):
        product = await self._make_product(db_session, admin_user)
        with pytest.raises(ResourceNotFoundException):
            await CatalogueService.get_design(db_session, admin_user, product.id, "design_does_not_exist")

    async def test_design_belonging_to_different_product_raises_404(self, db_session, admin_user):
        product_a = await self._make_product(db_session, admin_user, name="Product A")
        product_b = await self._make_product(db_session, admin_user, name="Product B")
        design_a = await CatalogueService.save_design(db_session, admin_user, product_a.id, CatalogueDesignSaveRequest(canvas=_text_only_canvas()))
        with pytest.raises(ResourceNotFoundException):
            await CatalogueService.get_design(db_session, admin_user, product_b.id, design_a.id)


class TestCatalogueRendering:
    """Phase B — the rendering engine, wired through CatalogueService's
    resolution (Product-layer image lookup) + persistence layer."""

    async def _product_with_image(self, db_session, admin_user, name="Render Test Product"):
        product = await CatalogueService.create_product(db_session, admin_user, ProductCreateRequest(name=name))
        image = await CatalogueService.upload_image(db_session, admin_user, product.id, _real_jpeg_upload())
        return product, image

    async def test_render_preview_does_not_persist_anything(self, db_session, admin_user):
        product = await CatalogueService.create_product(db_session, admin_user, ProductCreateRequest(name="Preview Test"))
        before = await CatalogueService.get_designs(db_session, admin_user, product.id)

        result = await CatalogueService.render_preview(
            db_session, admin_user, product.id, RenderPreviewRequest(canvas=_text_only_canvas())
        )
        assert result.content_base64
        assert result.content_type == "image/jpeg"

        after = await CatalogueService.get_designs(db_session, admin_user, product.id)
        assert len(after) == len(before) == 0  # preview never creates a CatalogueDesign row

    async def test_render_preview_resolves_product_layer_to_primary_image(self, db_session, admin_user):
        product, _image = await self._product_with_image(db_session, admin_user)
        result = await CatalogueService.render_preview(
            db_session, admin_user, product.id, RenderPreviewRequest(canvas=_product_layer_canvas())
        )
        assert result.width > 0 and result.height > 0

    async def test_render_preview_quality_affects_output_size(self, db_session, admin_user):
        """Product Studio redesign — Quality (Standard/High/Ultra) is a real
        render parameter now, not a cosmetic label."""
        product, _image = await self._product_with_image(db_session, admin_user)
        low = await CatalogueService.render_preview(
            db_session, admin_user, product.id,
            RenderPreviewRequest(canvas=_product_layer_canvas(), quality="STANDARD"),
        )
        high = await CatalogueService.render_preview(
            db_session, admin_user, product.id,
            RenderPreviewRequest(canvas=_product_layer_canvas(), quality="ULTRA"),
        )
        assert len(low.content_base64) < len(high.content_base64)

    async def test_export_design_persists_new_product_image(self, db_session, admin_user):
        product, _image = await self._product_with_image(db_session, admin_user)
        design = await CatalogueService.save_design(
            db_session, admin_user, product.id, CatalogueDesignSaveRequest(canvas=_product_layer_canvas())
        )
        before = await CatalogueService.get_product_by_id(db_session, admin_user, product.id)

        exported = await CatalogueService.export_design(
            db_session, admin_user, product.id, design.id, ExportDesignRequest()
        )
        assert exported.variant_type == "TEMPLATE"  # no output_preset -> generic bucket
        assert exported.source_image_id is None  # composed, not derived from one single parent image

        after = await CatalogueService.get_product_by_id(db_session, admin_user, product.id)
        assert after.image_count == before.image_count + 1

    async def test_export_design_with_output_preset_maps_to_dedicated_variant(self, db_session, admin_user):
        product, _image = await self._product_with_image(db_session, admin_user)
        design = await CatalogueService.save_design(
            db_session, admin_user, product.id, CatalogueDesignSaveRequest(canvas=_product_layer_canvas())
        )
        exported = await CatalogueService.export_design(
            db_session, admin_user, product.id, design.id, ExportDesignRequest(output_preset="INSTAGRAM_POST")
        )
        assert exported.variant_type == "INSTAGRAM"

    async def test_batch_render_across_products_creates_one_image_each(self, db_session, admin_user):
        product_a, _ = await self._product_with_image(db_session, admin_user, name="Batch A")
        product_b, _ = await self._product_with_image(db_session, admin_user, name="Batch B")

        images = await CatalogueService.batch_render(
            db_session, admin_user,
            BatchRenderRequest(template_key="LUXURY_WHITE", product_ids=[product_a.id, product_b.id]),
        )
        assert len(images) == 2
        assert {i.product_id for i in images} == {product_a.id, product_b.id}
        assert all(i.variant_type == "TEMPLATE" for i in images)

    async def test_batch_render_rejects_unknown_product_id(self, db_session, admin_user):
        product_a, _ = await self._product_with_image(db_session, admin_user)
        with pytest.raises(ResourceNotFoundException):
            await CatalogueService.batch_render(
                db_session, admin_user,
                BatchRenderRequest(template_key="LUXURY_WHITE", product_ids=[product_a.id, "prd_does_not_exist"]),
            )

    async def test_batch_render_rejects_unknown_template(self, db_session, admin_user):
        product_a, _ = await self._product_with_image(db_session, admin_user)
        with pytest.raises(ValidationException):
            await CatalogueService.batch_render(
                db_session, admin_user,
                BatchRenderRequest(template_key="NOT_A_REAL_TEMPLATE", product_ids=[product_a.id]),
            )

    async def test_generate_catalogue_pdf_returns_valid_pdf(self, db_session, admin_user):
        product_a, _ = await self._product_with_image(db_session, admin_user, name="PDF A")
        product_b, _ = await self._product_with_image(db_session, admin_user, name="PDF B")

        result = await CatalogueService.generate_catalogue_pdf(
            db_session, admin_user,
            CataloguePdfRequest(template_key="SQUARE", product_ids=[product_a.id, product_b.id]),
        )
        assert result.product_count == 2
        assert result.content_type == "application/pdf"
        import base64
        pdf_bytes = base64.b64decode(result.content_base64)
        assert pdf_bytes.startswith(b"%PDF")

    def test_list_templates_returns_all_twenty_six(self):
        templates = CatalogueService.list_templates()
        assert len(templates) == 26
        assert {t.key for t in templates} == {
            "LUXURY_WHITE", "LUXURY_BLACK", "ROYAL_BLUE", "WEDDING", "FESTIVAL",
            "INSTAGRAM", "WHATSAPP", "SQUARE", "PORTRAIT", "LANDSCAPE",
            "NECKLACE_LUXURY_WHITE", "NECKLACE_PREMIUM_MARBLE", "NECKLACE_DARK_LUXURY", "NECKLACE_BRIDAL",
            "RING_CENTERED", "RING_CIRCULAR_BALANCE", "RING_LUXURY_BLACK",
            "EARRINGS_BALANCED_SPACING", "EARRINGS_ELEGANT",
            "BRACELET_HORIZONTAL", "BRACELET_LUXURY",
            "PENDANT_PORTRAIT", "PENDANT_LUXURY",
            "BANGLE_CIRCULAR_SHOWCASE", "BANGLE_PREMIUM",
            "FULL_BLEED",
        }

    def test_list_templates_category_field(self):
        templates = CatalogueService.list_templates()
        by_key = {t.key: t for t in templates}
        assert by_key["LUXURY_WHITE"].category is None
        assert by_key["NECKLACE_BRIDAL"].category == "NECKLACE"
        assert by_key["RING_CENTERED"].category == "RING"
        assert by_key["BANGLE_PREMIUM"].category == "BANGLE"

    def test_list_output_presets_returns_all_nine(self):
        presets = CatalogueService.list_output_presets()
        assert len(presets) == 9
        instagram_post = next(p for p in presets if p.key == "INSTAGRAM_POST")
        assert (instagram_post.width, instagram_post.height) == (1080, 1080)
