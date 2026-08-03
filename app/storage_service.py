from __future__ import annotations

import hashlib
import io
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from .config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StoredObject:
    key: str
    size: int
    sha256: str


class StorageBackend:
    def put(self, key: str, content: bytes, content_type: str = "application/octet-stream") -> StoredObject:
        raise NotImplementedError

    def get(self, key: str) -> bytes:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError

    def exists(self, key: str) -> bool:
        raise NotImplementedError


class LocalStorage(StorageBackend):
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root not in path.parents and path != self.root:
            raise ValueError("Clave de almacenamiento inválida.")
        return path

    def put(self, key: str, content: bytes, content_type: str = "application/octet-stream") -> StoredObject:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return StoredObject(key=key, size=len(content), sha256=hashlib.sha256(content).hexdigest())

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()


class S3Storage(StorageBackend):
    def __init__(self):
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Falta instalar boto3 para usar almacenamiento S3.") from exc
        self.bucket = settings.s3_bucket
        if not self.bucket:
            raise RuntimeError("S3_BUCKET es obligatorio cuando STORAGE_BACKEND=s3.")
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url or None,
            aws_access_key_id=settings.s3_access_key_id or None,
            aws_secret_access_key=settings.s3_secret_access_key or None,
            region_name=settings.s3_region or None,
        )

    def put(self, key: str, content: bytes, content_type: str = "application/octet-stream") -> StoredObject:
        digest = hashlib.sha256(content).hexdigest()
        self.client.upload_fileobj(
            io.BytesIO(content),
            self.bucket,
            key,
            ExtraArgs={"ContentType": content_type, "Metadata": {"sha256": digest}},
        )
        return StoredObject(key=key, size=len(content), sha256=digest)

    def get(self, key: str) -> bytes:
        buffer = io.BytesIO()
        self.client.download_fileobj(self.bucket, key, buffer)
        return buffer.getvalue()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:  # pragma: no cover
            return False


def build_storage() -> StorageBackend:
    if settings.storage_backend.lower() == "s3":
        return S3Storage()
    return LocalStorage(Path(settings.local_storage_path))


storage = build_storage()
