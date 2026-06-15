"""Object storage abstraction over MinIO/S3 (aioboto3).

Stores only the object KEY in the DB; presigned URLs are minted on demand with a
short TTL. Failures raise ``StorageError`` so the caller degrades gracefully rather
than leaking boto internals. Key layout: ``applications/{app_id}/{doc_id}/{filename}``.
"""
from __future__ import annotations

import aioboto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.config import settings
from app.core.exceptions import StorageError
from app.core.logging import get_logger

log = get_logger(__name__)


class StorageService:
    def __init__(self) -> None:
        self._session = aioboto3.Session()
        self._bucket = settings.storage_bucket
        self._cfg = Config(signature_version="s3v4", s3={"addressing_style": "path"})

    def _client(self):
        return self._session.client(
            "s3",
            endpoint_url=settings.storage_endpoint_url,
            aws_access_key_id=settings.storage_access_key,
            aws_secret_access_key=settings.storage_secret_key,
            region_name=settings.storage_region,
            config=self._cfg,
        )

    @staticmethod
    def build_key(application_id: str, document_id: str, filename: str) -> str:
        safe = filename.replace("/", "_").replace("\\", "_")
        return f"applications/{application_id}/{document_id}/{safe}"

    async def ensure_bucket(self) -> None:
        """Create the bucket if missing (idempotent; dev/bootstrap helper)."""
        try:
            async with self._client() as s3:
                try:
                    await s3.head_bucket(Bucket=self._bucket)
                except ClientError:
                    await s3.create_bucket(Bucket=self._bucket)
        except (BotoCoreError, ClientError) as exc:
            log.error("storage.ensure_bucket_failed", error=str(exc))
            raise StorageError("Could not ensure storage bucket") from exc

    async def upload(self, key: str, data: bytes, content_type: str) -> None:
        try:
            async with self._client() as s3:
                await s3.put_object(
                    Bucket=self._bucket, Key=key, Body=data, ContentType=content_type
                )
        except (BotoCoreError, ClientError) as exc:
            log.error("storage.upload_failed", key=key, error=str(exc))
            raise StorageError("Document upload failed") from exc

    async def download(self, key: str) -> bytes:
        try:
            async with self._client() as s3:
                obj = await s3.get_object(Bucket=self._bucket, Key=key)
                async with obj["Body"] as stream:
                    return await stream.read()
        except (BotoCoreError, ClientError) as exc:
            log.error("storage.download_failed", key=key, error=str(exc))
            raise StorageError("Document download failed") from exc

    async def delete(self, key: str) -> None:
        """Best-effort delete (orphan cleanup). Never raises — failures are logged."""
        try:
            async with self._client() as s3:
                await s3.delete_object(Bucket=self._bucket, Key=key)
        except (BotoCoreError, ClientError) as exc:  # pragma: no cover - cleanup path
            log.error("storage.delete_failed", key=key, error=str(exc))

    async def presigned_download_url(self, key: str) -> str:
        try:
            async with self._client() as s3:
                return await s3.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self._bucket, "Key": key},
                    ExpiresIn=settings.presigned_url_ttl_seconds,
                )
        except (BotoCoreError, ClientError) as exc:
            log.error("storage.presign_failed", key=key, error=str(exc))
            raise StorageError("Could not generate download URL") from exc
