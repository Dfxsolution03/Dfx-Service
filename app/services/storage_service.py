"""
File storage abstraction for Module 20 (AI Catalogue Studio Foundation).

Mirrors the exact "extension point with a genuinely working default"
pattern app/services/email_service.py established in Module 18:
LocalDiskStorageProvider is the active default and is fully functional
(uploaded images really are stored and really are servable) so Products +
Media Library work end-to-end today with zero external infrastructure.
SupabaseStorageProvider is a real, working implementation that activates
automatically the moment SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY are set
in .env — "plug in Supabase Storage" means configuring settings, not
writing more code, same philosophy as SMTPEmailProvider.

Unlike payment_gateway.py's pure-stub pattern, storage needs a working
default *today* because Products/Media Library are real, functional
Module 20 requirements — not future extension points themselves.
"""

import asyncio
import os
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

import httpx

from app.core.config import settings
from app.core.logging import logger


class StorageProvider(ABC):
    @abstractmethod
    async def upload(
        self, *, tenant_id: str, file_name: str, content_type: str, file_bytes: bytes
    ) -> str:
        """Persists the file and returns a storage_path — a stable
        identifier this same provider can later resolve back to a URL via
        get_public_url(). Never overwrites: callers always pass a fresh,
        unique file_name."""
        raise NotImplementedError

    @abstractmethod
    def get_public_url(self, storage_path: str) -> str:
        """Resolves a previously-returned storage_path to a URL the
        frontend can load directly (an <img src>)."""
        raise NotImplementedError

    @abstractmethod
    async def delete(self, storage_path: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def download(self, storage_path: str) -> bytes:
        """Module 21 — reads a previously-uploaded file's bytes back, so a
        future real AIProvider has something to actually send to a vendor.
        Module 20 never needed this (it only ever wrote and served files)."""
        raise NotImplementedError


class LocalDiskStorageProvider(StorageProvider):
    """
    Default when Supabase Storage isn't configured. Writes under
    Backend/uploads/<tenant_id>/... and serves those files back via the
    /media static mount registered in app/main.py. Genuinely functional —
    not a stub — so this module doesn't block on external infrastructure.
    Not production-viable for a real multi-instance deployment (files don't
    survive a redeploy or scale past one server) — that's exactly why
    SupabaseStorageProvider exists as the upgrade path.
    """

    def __init__(self, base_dir: Optional[str] = None):
        self._base_dir = Path(base_dir or settings.LOCAL_UPLOAD_DIR)
        self._base_dir.mkdir(parents=True, exist_ok=True)

    async def upload(
        self, *, tenant_id: str, file_name: str, content_type: str, file_bytes: bytes
    ) -> str:
        safe_name = f"{uuid.uuid4().hex}_{Path(file_name).name}"
        relative_path = f"{tenant_id}/{safe_name}"
        target = self._base_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)

        def _write() -> None:
            target.write_bytes(file_bytes)

        await asyncio.to_thread(_write)
        return relative_path

    def get_public_url(self, storage_path: str) -> str:
        return f"{settings.BACKEND_PUBLIC_URL}/media/{storage_path}"

    async def delete(self, storage_path: str) -> None:
        target = self._base_dir / storage_path
        if target.exists():
            await asyncio.to_thread(target.unlink)

    async def download(self, storage_path: str) -> bytes:
        target = self._base_dir / storage_path
        return await asyncio.to_thread(target.read_bytes)


class SupabaseStorageProvider(StorageProvider):
    """
    Real implementation using Supabase Storage's REST API directly via
    httpx (already a dependency — see auth_service.py's precedent of
    preferring stdlib/existing deps over a new SDK, e.g. SMTPEmailProvider
    using smtplib instead of a mail-sending package). Only selected once
    SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are both set.
    """

    def __init__(self, base_url: str, service_role_key: str, bucket: str):
        self._base_url = base_url.rstrip("/")
        self._key = service_role_key
        self._bucket = bucket

    def _object_url(self, storage_path: str) -> str:
        return f"{self._base_url}/storage/v1/object/{self._bucket}/{storage_path}"

    async def upload(
        self, *, tenant_id: str, file_name: str, content_type: str, file_bytes: bytes
    ) -> str:
        safe_name = f"{uuid.uuid4().hex}_{Path(file_name).name}"
        storage_path = f"{tenant_id}/{safe_name}"
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                self._object_url(storage_path),
                headers={
                    "Authorization": f"Bearer {self._key}",
                    "apikey": self._key,
                    "Content-Type": content_type,
                    "x-upsert": "true",
                },
                content=file_bytes,
            )
            response.raise_for_status()
        return storage_path

    def get_public_url(self, storage_path: str) -> str:
        return f"{self._base_url}/storage/v1/object/public/{self._bucket}/{storage_path}"

    async def delete(self, storage_path: str) -> None:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.delete(
                self._object_url(storage_path),
                headers={"Authorization": f"Bearer {self._key}", "apikey": self._key},
            )
            if response.status_code not in (200, 204, 404):
                logger.warning(
                    f"Supabase Storage delete failed for '{storage_path}': "
                    f"{response.status_code} {response.text}"
                )

    async def download(self, storage_path: str) -> bytes:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                self._object_url(storage_path),
                headers={"Authorization": f"Bearer {self._key}", "apikey": self._key},
            )
            response.raise_for_status()
            return response.content


def get_storage_provider() -> StorageProvider:
    """Factory: real Supabase Storage once configured, local disk otherwise."""
    if settings.SUPABASE_URL and settings.SUPABASE_SERVICE_ROLE_KEY:
        return SupabaseStorageProvider(
            base_url=settings.SUPABASE_URL,
            service_role_key=settings.SUPABASE_SERVICE_ROLE_KEY,
            bucket=settings.SUPABASE_STORAGE_BUCKET,
        )
    return LocalDiskStorageProvider()
