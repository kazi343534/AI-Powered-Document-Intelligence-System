from __future__ import annotations

import logging
import shutil
from abc import ABC, abstractmethod
from functools import lru_cache
from pathlib import Path

import httpx

from .config import get_settings

logger = logging.getLogger(__name__)


class StorageError(RuntimeError):
    pass


class Storage(ABC):
    backend: str

    @abstractmethod
    def upload_file(self, local_path: Path, key: str, content_type: str) -> None: ...

    @abstractmethod
    def read_bytes(self, key: str) -> bytes: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def signed_url(self, key: str, expires_in: int = 3600) -> str | None: ...

    def local_path(self, key: str) -> Path | None:
        return None


class LocalStorage(Storage):
    backend = "local"

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        root = self.root.resolve()
        path = (root / key).resolve()
        if not path.is_relative_to(root):
            raise StorageError("invalid storage key")
        return path

    def upload_file(self, local_path: Path, key: str, content_type: str) -> None:
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        if local_path.resolve() != target:
            shutil.move(str(local_path), str(target))

    def read_bytes(self, key: str) -> bytes:
        path = self._path(key)
        if not path.exists():
            raise StorageError(f"object not found: {key}")
        return path.read_bytes()

    def delete(self, key: str) -> None:
        path = self._path(key)
        if path.exists():
            path.unlink()

    def signed_url(self, key: str, expires_in: int = 3600) -> str | None:
        return None

    def local_path(self, key: str) -> Path | None:
        return self._path(key)


class SupabaseStorage(Storage):
    backend = "supabase"

    def __init__(self, url: str, service_key: str, bucket: str):
        if not url or not service_key:
            raise StorageError("SUPABASE_URL and SUPABASE_SERVICE_KEY are required")
        self.url = url.rstrip("/")
        self.service_key = service_key
        self.bucket = bucket
        self.client = httpx.Client(
            base_url=f"{self.url}/storage/v1",
            headers={
                "Authorization": f"Bearer {service_key}",
                "apikey": service_key,
            },
            timeout=120.0,
        )
        self.ensure_bucket()

    def ensure_bucket(self) -> None:
        response = self.client.get(f"/bucket/{self.bucket}")
        if response.status_code == 200:
            return
        if response.status_code != 404:
            raise StorageError(
                f"cannot check Supabase bucket ({response.status_code}): {response.text[:300]}"
            )
        created = self.client.post(
            "/bucket",
            json={"id": self.bucket, "name": self.bucket, "public": False},
        )
        if created.status_code not in (200, 201):
            raise StorageError(
                f"cannot create Supabase bucket ({created.status_code}): {created.text[:300]}"
            )
        logger.info("created Supabase storage bucket %s", self.bucket)

    def upload_file(self, local_path: Path, key: str, content_type: str) -> None:
        with local_path.open("rb") as handle:
            response = self.client.post(
                f"/object/{self.bucket}/{key}",
                content=handle,
                headers={
                    "Content-Type": content_type,
                    "x-upsert": "true",
                    "cache-control": "no-store",
                },
            )
        if response.status_code not in (200, 201):
            raise StorageError(
                f"Supabase upload failed ({response.status_code}): {response.text[:300]}"
            )

    def read_bytes(self, key: str) -> bytes:
        response = self.client.get(f"/object/{self.bucket}/{key}")
        if response.status_code != 200:
            raise StorageError(
                f"Supabase download failed ({response.status_code}): {response.text[:300]}"
            )
        return response.content

    def delete(self, key: str) -> None:
        response = self.client.delete(f"/object/{self.bucket}/{key}")
        if response.status_code not in (200, 204, 404):
            logger.warning("Supabase delete failed (%s): %s", response.status_code, response.text[:200])

    def signed_url(self, key: str, expires_in: int = 3600) -> str | None:
        response = self.client.post(
            f"/object/sign/{self.bucket}/{key}",
            json={"expiresIn": expires_in},
        )
        if response.status_code != 200:
            logger.warning("Supabase sign failed (%s): %s", response.status_code, response.text[:200])
            return None
        signed = response.json().get("signedURL")
        if not signed:
            return None
        if signed.startswith("/"):
            return f"{self.url}/storage/v1{signed}"
        return signed


@lru_cache
def get_storage() -> Storage:
    settings = get_settings()
    if settings.storage_backend.lower() == "supabase":
        return SupabaseStorage(
            settings.supabase_url, settings.supabase_service_key, settings.supabase_bucket
        )
    return LocalStorage(settings.local_storage_path)


def reset_storage() -> None:
    get_storage.cache_clear()
