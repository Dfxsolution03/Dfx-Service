"""
DFX Solution API Tests — Catalogue Studio Module (Module 20)
=============================================================
"""

import io

import pytest

BASE = "/api/v1"


def _jpeg_bytes() -> bytes:
    return b"\xff\xd8\xff\xe0fakejpegbytesfortest"


def _real_jpeg_bytes(size=(300, 200), color=(120, 90, 40)) -> bytes:
    """A genuinely decodable JPEG — needed for the Image Editor endpoints,
    which actually run Pillow/OpenCV against the bytes (unlike most of this
    file's fake-byte uploads, which only ever get stored/served, never
    decoded)."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", size, color=color).save(buffer, format="JPEG")
    return buffer.getvalue()


class TestProductAuthAndRoleGating:
    async def test_list_products_requires_auth(self, client):
        r = await client.get(f"{BASE}/catalogue/products")
        assert r.status_code == 401

    async def test_customer_cannot_list_products(self, client, customer_auth_headers):
        r = await client.get(f"{BASE}/catalogue/products", headers=customer_auth_headers)
        assert r.status_code == 403

    async def test_superadmin_cannot_list_products(self, client, superadmin_auth_headers):
        r = await client.get(f"{BASE}/catalogue/products", headers=superadmin_auth_headers)
        assert r.status_code == 403

    async def test_admin_can_list_products(self, client, admin_auth_headers):
        r = await client.get(f"{BASE}/catalogue/products", headers=admin_auth_headers)
        assert r.status_code == 200
        assert r.json()["success"] is True


class TestProductCRUD:
    async def test_create_list_get_update_deactivate_product(self, client, admin_auth_headers):
        create_resp = await client.post(
            f"{BASE}/catalogue/products",
            headers=admin_auth_headers,
            json={"name": "Gold Bangle Set", "category": "Bangles"},
        )
        assert create_resp.status_code == 201
        product = create_resp.json()["data"]["product"]
        product_id = product["id"]
        assert product["is_active"] is True
        assert product["image_count"] == 0

        list_resp = await client.get(f"{BASE}/catalogue/products", headers=admin_auth_headers)
        assert any(p["id"] == product_id for p in list_resp.json()["data"]["products"])

        get_resp = await client.get(f"{BASE}/catalogue/products/{product_id}", headers=admin_auth_headers)
        assert get_resp.status_code == 200
        assert get_resp.json()["data"]["product"]["name"] == "Gold Bangle Set"

        update_resp = await client.put(
            f"{BASE}/catalogue/products/{product_id}",
            headers=admin_auth_headers,
            json={"name": "Renamed Bangle Set"},
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["data"]["product"]["name"] == "Renamed Bangle Set"

        delete_resp = await client.delete(
            f"{BASE}/catalogue/products/{product_id}", headers=admin_auth_headers
        )
        assert delete_resp.status_code == 200

        after = await client.get(f"{BASE}/catalogue/products/{product_id}", headers=admin_auth_headers)
        assert after.json()["data"]["product"]["is_active"] is False

    async def test_get_nonexistent_product_returns_404(self, client, admin_auth_headers):
        r = await client.get(f"{BASE}/catalogue/products/prd_does_not_exist", headers=admin_auth_headers)
        assert r.status_code == 404

    async def test_create_product_validates_name_length(self, client, admin_auth_headers):
        r = await client.post(
            f"{BASE}/catalogue/products", headers=admin_auth_headers, json={"name": "A"}
        )
        assert r.status_code in [400, 422]

    async def test_create_and_update_product_commercial_fields(self, client, admin_auth_headers):
        """Product Studio redesign — purity/price/weight_grams/tags via the
        real HTTP request shape the frontend actually sends."""
        create_resp = await client.post(
            f"{BASE}/catalogue/products",
            headers=admin_auth_headers,
            json={
                "name": "18K Diamond Ring",
                "purity": "18K",
                "price": 89999.99,
                "weight_grams": 6.5,
                "tags": ["diamond", "ring", "engagement"],
            },
        )
        assert create_resp.status_code == 201
        product = create_resp.json()["data"]["product"]
        assert product["purity"] == "18K"
        assert product["price"] == 89999.99
        assert product["weight_grams"] == 6.5
        assert product["tags"] == ["diamond", "ring", "engagement"]

        update_resp = await client.put(
            f"{BASE}/catalogue/products/{product['id']}",
            headers=admin_auth_headers,
            json={"tags": ["clearance"]},
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["data"]["product"]["tags"] == ["clearance"]


class TestImageUploadAndGallery:
    async def _create_product(self, client, admin_auth_headers, name="Image Test Product"):
        r = await client.post(
            f"{BASE}/catalogue/products", headers=admin_auth_headers, json={"name": name}
        )
        return r.json()["data"]["product"]["id"]

    async def test_upload_image_creates_original_and_primary(self, client, admin_auth_headers):
        product_id = await self._create_product(client, admin_auth_headers)

        r = await client.post(
            f"{BASE}/catalogue/products/{product_id}/images",
            headers=admin_auth_headers,
            files={"file": ("test.jpg", _jpeg_bytes(), "image/jpeg")},
        )
        assert r.status_code == 201
        image = r.json()["data"]["image"]
        assert image["variant_type"] == "ORIGINAL"
        assert image["is_primary"] is True
        assert image["url"]

    async def test_upload_with_shot_type_persists_it(self, client, admin_auth_headers):
        """Product Studio redesign — Step 2's shot-type tagging (Front/Back/
        Side/Top/45°/Lifestyle/Macro) via the real multipart form field."""
        product_id = await self._create_product(client, admin_auth_headers)
        r = await client.post(
            f"{BASE}/catalogue/products/{product_id}/images",
            headers=admin_auth_headers,
            files={"file": ("front.jpg", _jpeg_bytes(), "image/jpeg")},
            data={"shot_type": "FRONT"},
        )
        assert r.status_code == 201
        assert r.json()["data"]["image"]["shot_type"] == "FRONT"

    async def test_upload_rejects_non_image_content_type(self, client, admin_auth_headers):
        product_id = await self._create_product(client, admin_auth_headers)
        r = await client.post(
            f"{BASE}/catalogue/products/{product_id}/images",
            headers=admin_auth_headers,
            files={"file": ("doc.pdf", b"%PDF-fake", "application/pdf")},
        )
        assert r.status_code == 400

    async def test_set_primary_and_reorder_and_delete(self, client, admin_auth_headers):
        product_id = await self._create_product(client, admin_auth_headers)

        img1 = (
            await client.post(
                f"{BASE}/catalogue/products/{product_id}/images",
                headers=admin_auth_headers,
                files={"file": ("a.jpg", _jpeg_bytes(), "image/jpeg")},
            )
        ).json()["data"]["image"]
        img2 = (
            await client.post(
                f"{BASE}/catalogue/products/{product_id}/images",
                headers=admin_auth_headers,
                files={"file": ("b.jpg", _jpeg_bytes(), "image/jpeg")},
            )
        ).json()["data"]["image"]

        set_primary_resp = await client.put(
            f"{BASE}/catalogue/products/{product_id}/images/{img2['id']}/primary",
            headers=admin_auth_headers,
        )
        assert set_primary_resp.status_code == 200

        reorder_resp = await client.put(
            f"{BASE}/catalogue/products/{product_id}/images/reorder",
            headers=admin_auth_headers,
            json={"image_ids": [img2["id"], img1["id"]]},
        )
        assert reorder_resp.status_code == 200

        delete_resp = await client.delete(
            f"{BASE}/catalogue/products/{product_id}/images/{img1['id']}",
            headers=admin_auth_headers,
        )
        assert delete_resp.status_code == 200

        product_resp = await client.get(
            f"{BASE}/catalogue/products/{product_id}", headers=admin_auth_headers
        )
        images = product_resp.json()["data"]["product"]["images"]
        assert len(images) == 1
        assert images[0]["id"] == img2["id"]


class TestMediaLibraryAndStorageStatus:
    async def test_media_library_returns_200(self, client, admin_auth_headers):
        r = await client.get(f"{BASE}/catalogue/media", headers=admin_auth_headers)
        assert r.status_code == 200
        assert "images" in r.json()["data"]

    async def test_storage_status_reports_local_disk_by_default(self, client, admin_auth_headers):
        r = await client.get(f"{BASE}/catalogue/storage-status", headers=admin_auth_headers)
        assert r.status_code == 200
        assert r.json()["data"]["provider"] in ["local_disk", "supabase"]


class TestEnhanceEndpointHonestlyUnconfigured:
    async def test_enhance_returns_400_not_configured(self, client, admin_auth_headers):
        create_resp = await client.post(
            f"{BASE}/catalogue/products", headers=admin_auth_headers, json={"name": "Enhance Test"}
        )
        product_id = create_resp.json()["data"]["product"]["id"]
        upload_resp = await client.post(
            f"{BASE}/catalogue/products/{product_id}/images",
            headers=admin_auth_headers,
            files={"file": ("test.jpg", _jpeg_bytes(), "image/jpeg")},
        )
        image_id = upload_resp.json()["data"]["image"]["id"]

        r = await client.post(
            f"{BASE}/catalogue/products/{product_id}/images/{image_id}/enhance",
            headers=admin_auth_headers,
            json={"enhancement_type": "REMOVE_BACKGROUND"},
        )
        assert r.status_code == 400
        assert "not yet configured" in r.json()["message"].lower()


class TestTenantIsolation:
    async def test_admin_cannot_see_other_tenants_products(self, client, admin_auth_headers, db_session):
        from tests.conftest import make_auth_headers
        from app.core.security import create_access_token
        import uuid

        create_resp = await client.post(
            f"{BASE}/catalogue/products", headers=admin_auth_headers, json={"name": "Tenant A Product"}
        )
        product_id = create_resp.json()["data"]["product"]["id"]

        # A second admin in a different tenant must not be able to fetch it.
        from app.models.auth import User, Role
        from sqlalchemy import select
        from app.core.security import hash_password

        stmt = select(Role).where(Role.name == "Admin")
        role = (await db_session.execute(stmt)).scalar_one()

        other_tenant_id = "tnt_test_other_" + uuid.uuid4().hex[:8]
        from app.models.auth import Tenant

        db_session.add(Tenant(id=other_tenant_id, name="Other Tenant", slug=other_tenant_id, status="Active"))
        await db_session.flush()

        other_admin = User(
            id=f"usr_test_{uuid.uuid4().hex[:12]}",
            tenant_id=other_tenant_id,
            role_id=role.id,
            email=f"other_{uuid.uuid4().hex[:8]}@catalogue-test.com",
            phone=None,
            hashed_password=hash_password("Passw0rd123"),
            name="Other Admin",
            is_active=True,
        )
        db_session.add(other_admin)
        await db_session.commit()

        token = create_access_token(subject=other_admin.id, tenant_id=other_tenant_id, role="Admin")
        headers = make_auth_headers(token)

        r = await client.get(f"{BASE}/catalogue/products/{product_id}", headers=headers)
        assert r.status_code == 404


class TestPipelineStatusEndpoint:
    async def test_pipeline_status_requires_auth(self, client):
        r = await client.get(f"{BASE}/catalogue/products/prd_x/images/img_x/pipeline")
        assert r.status_code == 401

    async def test_pipeline_status_returns_5_stages(self, client, admin_auth_headers):
        create_resp = await client.post(
            f"{BASE}/catalogue/products", headers=admin_auth_headers, json={"name": "Pipeline API Test"}
        )
        product_id = create_resp.json()["data"]["product"]["id"]
        upload_resp = await client.post(
            f"{BASE}/catalogue/products/{product_id}/images",
            headers=admin_auth_headers,
            files={"file": ("test.jpg", _jpeg_bytes(), "image/jpeg")},
        )
        image_id = upload_resp.json()["data"]["image"]["id"]

        r = await client.get(
            f"{BASE}/catalogue/products/{product_id}/images/{image_id}/pipeline", headers=admin_auth_headers
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data["stages"]) == 5
        assert data["stages"][0]["variant_type"] == "ORIGINAL"
        assert data["stages"][0]["completed"] is True
        assert data["ai_provider_configured"] is False


class TestImageEditorEndpoints:
    """Jewellery Catalogue & Marketing Studio, Phase A — real, local
    Pillow/OpenCV editing via /edit/preview (ephemeral) and /edit/save
    (persists a new EDITED variant)."""

    async def _create_product_with_image(self, client, admin_auth_headers, name="Edit Endpoint Test"):
        create_resp = await client.post(
            f"{BASE}/catalogue/products", headers=admin_auth_headers, json={"name": name}
        )
        product_id = create_resp.json()["data"]["product"]["id"]
        upload_resp = await client.post(
            f"{BASE}/catalogue/products/{product_id}/images",
            headers=admin_auth_headers,
            files={"file": ("test.jpg", _real_jpeg_bytes(), "image/jpeg")},
        )
        image_id = upload_resp.json()["data"]["image"]["id"]
        return product_id, image_id

    async def test_preview_requires_auth(self, client):
        r = await client.post(
            f"{BASE}/catalogue/products/prd_x/images/img_x/edit/preview",
            json={"operations": [{"type": "BRIGHTNESS", "factor": 1.0}]},
        )
        assert r.status_code == 401

    async def test_customer_cannot_preview_edit(self, client, customer_auth_headers):
        r = await client.post(
            f"{BASE}/catalogue/products/prd_x/images/img_x/edit/preview",
            headers=customer_auth_headers,
            json={"operations": [{"type": "BRIGHTNESS", "factor": 1.0}]},
        )
        assert r.status_code == 403

    async def test_preview_returns_base64_and_does_not_persist(self, client, admin_auth_headers):
        product_id, image_id = await self._create_product_with_image(client, admin_auth_headers)

        before = await client.get(f"{BASE}/catalogue/products/{product_id}", headers=admin_auth_headers)
        before_count = before.json()["data"]["product"]["image_count"]

        r = await client.post(
            f"{BASE}/catalogue/products/{product_id}/images/{image_id}/edit/preview",
            headers=admin_auth_headers,
            json={"operations": [{"type": "BRIGHTNESS", "factor": 1.2}, {"type": "BLUR", "radius": 2.0}]},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["content_base64"]
        assert data["content_type"] in ("image/jpeg", "image/png")
        assert data["width"] > 0 and data["height"] > 0

        after = await client.get(f"{BASE}/catalogue/products/{product_id}", headers=admin_auth_headers)
        assert after.json()["data"]["product"]["image_count"] == before_count

    async def test_save_creates_new_edited_image_variant(self, client, admin_auth_headers):
        product_id, image_id = await self._create_product_with_image(client, admin_auth_headers)

        r = await client.post(
            f"{BASE}/catalogue/products/{product_id}/images/{image_id}/edit/save",
            headers=admin_auth_headers,
            json={
                "operations": [
                    {"type": "CROP", "x": 0, "y": 0, "width": 200, "height": 150},
                    {"type": "CONTRAST", "factor": 1.1},
                ]
            },
        )
        assert r.status_code == 201
        image = r.json()["data"]["image"]
        assert image["variant_type"] == "EDITED"
        assert image["source_image_id"] == image_id

        product_resp = await client.get(f"{BASE}/catalogue/products/{product_id}", headers=admin_auth_headers)
        variant_types = {i["variant_type"] for i in product_resp.json()["data"]["product"]["images"]}
        assert "EDITED" in variant_types
        assert "ORIGINAL" in variant_types  # source untouched

    async def test_background_replace_transparent_via_endpoint(self, client, admin_auth_headers):
        product_id, image_id = await self._create_product_with_image(client, admin_auth_headers)
        r = await client.post(
            f"{BASE}/catalogue/products/{product_id}/images/{image_id}/edit/preview",
            headers=admin_auth_headers,
            json={"operations": [{"type": "BACKGROUND_REPLACE", "mode": "TRANSPARENT"}]},
        )
        assert r.status_code == 200
        assert r.json()["data"]["content_type"] == "image/png"

    async def test_invalid_operation_params_return_400(self, client, admin_auth_headers):
        product_id, image_id = await self._create_product_with_image(client, admin_auth_headers)
        r = await client.post(
            f"{BASE}/catalogue/products/{product_id}/images/{image_id}/edit/preview",
            headers=admin_auth_headers,
            # ROTATE with no degrees
            json={"operations": [{"type": "ROTATE"}]},
        )
        assert r.status_code == 400

    async def test_edit_nonexistent_image_returns_404(self, client, admin_auth_headers):
        product_id, _image_id = await self._create_product_with_image(client, admin_auth_headers)
        r = await client.post(
            f"{BASE}/catalogue/products/{product_id}/images/img_does_not_exist/edit/preview",
            headers=admin_auth_headers,
            json={"operations": [{"type": "BRIGHTNESS", "factor": 1.0}]},
        )
        assert r.status_code == 404

    async def test_empty_operations_list_returns_422(self, client, admin_auth_headers):
        product_id, image_id = await self._create_product_with_image(client, admin_auth_headers)
        r = await client.post(
            f"{BASE}/catalogue/products/{product_id}/images/{image_id}/edit/preview",
            headers=admin_auth_headers,
            json={"operations": []},
        )
        assert r.status_code in [400, 422]


class TestAIProviderStatusEndpoint:
    async def test_requires_auth(self, client):
        r = await client.get(f"{BASE}/catalogue/ai-provider-status")
        assert r.status_code == 401

    async def test_customer_cannot_access(self, client, customer_auth_headers):
        r = await client.get(f"{BASE}/catalogue/ai-provider-status", headers=customer_auth_headers)
        assert r.status_code == 403


def _text_only_canvas_dict(w=400, h=300) -> dict:
    return {
        "canvas_width": w, "canvas_height": h,
        "layers": [
            {"id": "bg", "type": "BACKGROUND", "x": 0, "y": 0, "width": w, "height": h, "z_index": 0, "color": "#FFFFFF"},
            {"id": "txt", "type": "TEXT", "x": 20, "y": 20, "width": w - 40, "height": 60, "z_index": 10, "text": "Hello", "font_family": "POPPINS", "font_size": 24},
        ],
    }


def _product_layer_canvas_dict(w=400, h=300) -> dict:
    return {
        "canvas_width": w, "canvas_height": h,
        "layers": [
            {"id": "bg", "type": "BACKGROUND", "x": 0, "y": 0, "width": w, "height": h, "z_index": 0, "color": "#FFFFFF"},
            {"id": "prod", "type": "PRODUCT", "x": 20, "y": 20, "width": w - 40, "height": h - 40, "z_index": 10, "image_id": None},
        ],
    }


class TestTemplateAndPresetEndpoints:
    async def test_list_templates_requires_auth(self, client):
        r = await client.get(f"{BASE}/catalogue/templates")
        assert r.status_code == 401

    async def test_list_templates_returns_twenty_six(self, client, admin_auth_headers):
        r = await client.get(f"{BASE}/catalogue/templates", headers=admin_auth_headers)
        assert r.status_code == 200
        assert len(r.json()["data"]["templates"]) == 26

    async def test_list_output_presets_returns_nine(self, client, admin_auth_headers):
        r = await client.get(f"{BASE}/catalogue/output-presets", headers=admin_auth_headers)
        assert r.status_code == 200
        assert len(r.json()["data"]["presets"]) == 9


class TestDesignVersioningEndpoints:
    async def _create_product(self, client, admin_auth_headers, name="Design Endpoint Test"):
        r = await client.post(f"{BASE}/catalogue/products", headers=admin_auth_headers, json={"name": name})
        return r.json()["data"]["product"]["id"]

    async def test_save_requires_auth(self, client):
        r = await client.post(
            f"{BASE}/catalogue/products/prd_x/designs", json={"canvas": _text_only_canvas_dict()}
        )
        assert r.status_code == 401

    async def test_save_then_list_then_get(self, client, admin_auth_headers):
        product_id = await self._create_product(client, admin_auth_headers)

        save_resp = await client.post(
            f"{BASE}/catalogue/products/{product_id}/designs",
            headers=admin_auth_headers,
            json={"name": "Draft", "canvas": _text_only_canvas_dict()},
        )
        assert save_resp.status_code == 201
        design = save_resp.json()["data"]["design"]
        assert design["version"] == 1
        assert design["source_design_id"] is None

        list_resp = await client.get(f"{BASE}/catalogue/products/{product_id}/designs", headers=admin_auth_headers)
        assert list_resp.status_code == 200
        assert len(list_resp.json()["data"]["designs"]) == 1

        get_resp = await client.get(
            f"{BASE}/catalogue/products/{product_id}/designs/{design['id']}", headers=admin_auth_headers
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["data"]["design"]["name"] == "Draft"

    async def test_restore_and_duplicate(self, client, admin_auth_headers):
        product_id = await self._create_product(client, admin_auth_headers)
        v1 = (
            await client.post(
                f"{BASE}/catalogue/products/{product_id}/designs",
                headers=admin_auth_headers,
                json={"name": "V1", "canvas": _text_only_canvas_dict()},
            )
        ).json()["data"]["design"]
        await client.post(
            f"{BASE}/catalogue/products/{product_id}/designs",
            headers=admin_auth_headers,
            json={"name": "V2", "canvas": _text_only_canvas_dict()},
        )

        restore_resp = await client.post(
            f"{BASE}/catalogue/products/{product_id}/designs/{v1['id']}/restore",
            headers=admin_auth_headers,
            json={},
        )
        assert restore_resp.status_code == 201
        restored = restore_resp.json()["data"]["design"]
        assert restored["version"] == 3
        assert restored["source_design_id"] == v1["id"]
        assert restored["name"] == "V1"

        duplicate_resp = await client.post(
            f"{BASE}/catalogue/products/{product_id}/designs/{v1['id']}/duplicate",
            headers=admin_auth_headers,
            json={},
        )
        assert duplicate_resp.status_code == 201
        assert duplicate_resp.json()["data"]["design"]["name"] == "V1 (Copy)"

    async def test_get_nonexistent_design_returns_404(self, client, admin_auth_headers):
        product_id = await self._create_product(client, admin_auth_headers)
        r = await client.get(
            f"{BASE}/catalogue/products/{product_id}/designs/design_does_not_exist", headers=admin_auth_headers
        )
        assert r.status_code == 404


class TestRenderAndExportEndpoints:
    async def _create_product_with_image(self, client, admin_auth_headers, name="Render Endpoint Test"):
        create_resp = await client.post(f"{BASE}/catalogue/products", headers=admin_auth_headers, json={"name": name})
        product_id = create_resp.json()["data"]["product"]["id"]
        await client.post(
            f"{BASE}/catalogue/products/{product_id}/images",
            headers=admin_auth_headers,
            files={"file": ("test.jpg", _real_jpeg_bytes(), "image/jpeg")},
        )
        return product_id

    async def test_render_preview_route_is_not_swallowed_by_design_id_route(self, client, admin_auth_headers):
        """Route-precedence sanity check: /designs/render/preview must reach
        the preview handler, not 404/422 as if 'render' were being parsed as
        a {design_id} path segment."""
        product_id = await self._create_product_with_image(client, admin_auth_headers)
        r = await client.post(
            f"{BASE}/catalogue/products/{product_id}/designs/render/preview",
            headers=admin_auth_headers,
            json={"canvas": _text_only_canvas_dict()},
        )
        assert r.status_code == 200
        assert r.json()["data"]["content_base64"]

    async def test_render_preview_does_not_persist(self, client, admin_auth_headers):
        product_id = await self._create_product_with_image(client, admin_auth_headers)
        await client.post(
            f"{BASE}/catalogue/products/{product_id}/designs/render/preview",
            headers=admin_auth_headers,
            json={"canvas": _text_only_canvas_dict()},
        )
        list_resp = await client.get(f"{BASE}/catalogue/products/{product_id}/designs", headers=admin_auth_headers)
        assert list_resp.json()["data"]["designs"] == []

    async def test_export_design_persists_new_image(self, client, admin_auth_headers):
        product_id = await self._create_product_with_image(client, admin_auth_headers)
        design = (
            await client.post(
                f"{BASE}/catalogue/products/{product_id}/designs",
                headers=admin_auth_headers,
                json={"canvas": _product_layer_canvas_dict()},
            )
        ).json()["data"]["design"]

        export_resp = await client.post(
            f"{BASE}/catalogue/products/{product_id}/designs/{design['id']}/export",
            headers=admin_auth_headers,
            json={},
        )
        assert export_resp.status_code == 201
        image = export_resp.json()["data"]["image"]
        assert image["variant_type"] == "TEMPLATE"

        product_resp = await client.get(f"{BASE}/catalogue/products/{product_id}", headers=admin_auth_headers)
        variant_types = {i["variant_type"] for i in product_resp.json()["data"]["product"]["images"]}
        assert "TEMPLATE" in variant_types


class TestBatchRenderAndPdfEndpoints:
    async def _create_product_with_image(self, client, admin_auth_headers, name="Batch Endpoint Test"):
        create_resp = await client.post(f"{BASE}/catalogue/products", headers=admin_auth_headers, json={"name": name})
        product_id = create_resp.json()["data"]["product"]["id"]
        await client.post(
            f"{BASE}/catalogue/products/{product_id}/images",
            headers=admin_auth_headers,
            files={"file": ("test.jpg", _real_jpeg_bytes(), "image/jpeg")},
        )
        return product_id

    async def test_batch_render_requires_auth(self, client):
        r = await client.post(f"{BASE}/catalogue/designs/batch-render", json={"template_key": "SQUARE", "product_ids": ["prd_x"]})
        assert r.status_code == 401

    async def test_batch_render_two_products(self, client, admin_auth_headers):
        product_a = await self._create_product_with_image(client, admin_auth_headers, "Batch A")
        product_b = await self._create_product_with_image(client, admin_auth_headers, "Batch B")

        r = await client.post(
            f"{BASE}/catalogue/designs/batch-render",
            headers=admin_auth_headers,
            json={"template_key": "LUXURY_WHITE", "product_ids": [product_a, product_b]},
        )
        assert r.status_code == 201
        images = r.json()["data"]["images"]
        assert len(images) == 2

    async def test_catalogue_pdf_returns_base64_pdf(self, client, admin_auth_headers):
        product_a = await self._create_product_with_image(client, admin_auth_headers, "PDF A")

        r = await client.post(
            f"{BASE}/catalogue/designs/catalogue-pdf",
            headers=admin_auth_headers,
            json={"template_key": "SQUARE", "product_ids": [product_a]},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["content_type"] == "application/pdf"
        assert data["product_count"] == 1

        import base64
        assert base64.b64decode(data["content_base64"]).startswith(b"%PDF")

    async def test_admin_gets_stub_not_configured(self, client, admin_auth_headers):
        r = await client.get(f"{BASE}/catalogue/ai-provider-status", headers=admin_auth_headers)
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["provider"] == "Stub"
        assert data["configured"] is False
