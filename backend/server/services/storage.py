"""Object storage abstraction: local disk (dev) and S3-compatible (Cloudflare R2).

Keys are validated everywhere; the DB stores keys, never long-lived URLs. URLs
are derived at read time so public-CDN and signed-URL modes can be switched by
configuration alone.
"""

from __future__ import annotations

import mimetypes
import re
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import structlog

from server.core.config import Settings, get_settings

log = structlog.get_logger(__name__)

_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-/]{0,400}$")
_FILENAME_SAFE = re.compile(r"[^A-Za-z0-9._\-]+")


class StorageError(Exception):
    pass


class UnsafeKeyError(StorageError):
    pass


def validate_key(key: str) -> str:
    if not _KEY_RE.match(key) or ".." in key.split("/") or "//" in key or key.endswith("/"):
        raise UnsafeKeyError("unsafe storage key")
    if any(part in ("", ".", "..") for part in key.split("/")):
        raise UnsafeKeyError("unsafe storage key")
    return key


def sanitize_filename(name: str, default: str = "file") -> str:
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    base = _FILENAME_SAFE.sub("_", base).strip("._") or default
    return base[:100]


def output_key(generation_id: Any, filename: str) -> str:
    return validate_key(f"generations/{generation_id}/{sanitize_filename(filename)}")


@dataclass
class PresignedUpload:
    method: str
    url: str
    headers: dict[str, str]
    key: str
    expires_in: int


class StorageService(ABC):
    backend: str

    @abstractmethod
    def put_file(self, key: str, path: Path, content_type: str | None = None) -> None: ...

    @abstractmethod
    def url_for(self, key: str) -> str | None: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def size(self, key: str) -> int | None: ...

    @abstractmethod
    def get_file(self, key: str, dest: Path) -> None: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    def presign_upload(self, key: str, content_type: str, expires_in: int) -> PresignedUpload:
        raise StorageError("presigned uploads are not supported by this storage backend")

    @property
    def supports_presign(self) -> bool:
        return False

    def healthcheck(self) -> bool:
        return True


class LocalStorage(StorageService):
    backend = "local"

    def __init__(self, root: Path, url_prefix: str = "/media"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.url_prefix = url_prefix.rstrip("/")

    def _path(self, key: str) -> Path:
        validate_key(key)
        resolved = (self.root / key).resolve()
        if not resolved.is_relative_to(self.root.resolve()):
            raise UnsafeKeyError("key escapes storage root")
        return resolved

    def resolve(self, key: str) -> Path:
        return self._path(key)

    def put_file(self, key: str, path: Path, content_type: str | None = None) -> None:
        dest = self._path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        shutil.copyfile(path, tmp)
        tmp.replace(dest)

    def url_for(self, key: str) -> str | None:
        validate_key(key)
        return f"{self.url_prefix}/{key}"

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def size(self, key: str) -> int | None:
        p = self._path(key)
        return p.stat().st_size if p.is_file() else None

    def get_file(self, key: str, dest: Path) -> None:
        src = self._path(key)
        if not src.is_file():
            raise StorageError("object not found")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


class R2Storage(StorageService):
    backend = "r2"

    def __init__(self, settings: Settings, client: Any | None = None):
        self.bucket = settings.r2_bucket
        self.public_base = (settings.r2_public_base_url or "").rstrip("/") or None
        self.signed_ttl = settings.signed_url_ttl_seconds
        if client is None:
            import boto3
            from botocore.config import Config

            client = boto3.client(
                "s3",
                endpoint_url=settings.r2_endpoint_url,
                aws_access_key_id=settings.r2_access_key_id.get_secret_value(),
                aws_secret_access_key=settings.r2_secret_access_key.get_secret_value(),
                region_name=settings.r2_region,
                # path-style addressing (endpoint/bucket/key): required by Supabase, accepted by R2 and MinIO
                config=Config(signature_version="s3v4", s3={"addressing_style": "path"},
                              retries={"max_attempts": 4, "mode": "standard"}),
            )
        self.client = client

    @property
    def supports_presign(self) -> bool:
        return True

    def put_file(self, key: str, path: Path, content_type: str | None = None) -> None:
        validate_key(key)
        ctype = content_type or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        try:
            self.client.upload_file(str(path), self.bucket, key, ExtraArgs={"ContentType": ctype})
        except Exception as exc:  # boto raises many types; callers only care that it failed
            raise StorageError("upload failed") from exc

    def url_for(self, key: str) -> str | None:
        validate_key(key)
        if self.public_base:
            return f"{self.public_base}/{key}"
        return self.client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=self.signed_ttl
        )

    def exists(self, key: str) -> bool:
        validate_key(key)
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def delete(self, key: str) -> None:
        validate_key(key)
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def size(self, key: str) -> int | None:
        validate_key(key)
        try:
            return int(self.client.head_object(Bucket=self.bucket, Key=key)["ContentLength"])
        except Exception:
            return None

    def get_file(self, key: str, dest: Path) -> None:
        validate_key(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.client.download_file(self.bucket, key, str(dest))  # streams to disk, never into RAM
        except Exception as exc:
            raise StorageError("download failed") from exc

    def presign_upload(self, key: str, content_type: str, expires_in: int) -> PresignedUpload:
        validate_key(key)
        url = self.client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self.bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=expires_in,
        )
        return PresignedUpload("PUT", url, {"Content-Type": content_type}, key, expires_in)

    def healthcheck(self) -> bool:
        try:
            self.client.head_bucket(Bucket=self.bucket)
            return True
        except Exception:
            return False


def build_storage(settings: Settings) -> StorageService:
    if settings.uses_object_storage:
        return R2Storage(settings)
    return LocalStorage(settings.local_storage_path)


@lru_cache
def get_storage() -> StorageService:
    return build_storage(get_settings())


def reset_storage_cache() -> None:
    get_storage.cache_clear()
