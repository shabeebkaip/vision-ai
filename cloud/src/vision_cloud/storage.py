"""Object storage for snapshots, clips, device logs and model files.

Edge boxes upload straight to storage with pre-signed POST forms (the size limit is part of the
signed policy) and then call the API's finalise endpoint, which checks the object exists. The API
never streams media itself.

Key layout (CLD-06): `{org}/{site}/{camera}/{yyyy}/{mm}/{dd}/{event}/snapshot.jpg|clip.mp4`, all ids
being UUIDs, so object keys carry no customer names. Lifecycle rules, server-side encryption policy
and signed view URLs for the dashboard are finished in CLD-06.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from vision_cloud.settings import CloudSettings

SNAPSHOT_TYPE = "image/jpeg"
CLIP_TYPE = "video/mp4"


@dataclass
class PresignedPost:
    url: str
    fields: dict[str, str]
    key: str
    expires_at: datetime
    max_bytes: int


@dataclass
class StoredObject:
    size: int
    content_type: str | None = None


class ObjectStore(Protocol):
    def presign_post(
        self, key: str, content_type: str, max_bytes: int, ttl_s: int
    ) -> PresignedPost: ...

    def presign_get(self, key: str, ttl_s: int) -> str: ...

    def head(self, key: str) -> StoredObject | None: ...


def event_media_key(
    org_id: uuid.UUID,
    site_id: uuid.UUID,
    camera_id: uuid.UUID,
    triggered_at: datetime,
    event_id: uuid.UUID,
    kind: str,
) -> str:
    t = triggered_at.astimezone(timezone.utc)
    name = {"snapshot": "snapshot.jpg", "clip": "clip.mp4"}[kind]
    return f"{org_id}/{site_id}/{camera_id}/{t:%Y/%m/%d}/{event_id}/{name}"


def device_log_key(
    org_id: uuid.UUID, site_id: uuid.UUID, device_id: uuid.UUID, at: datetime
) -> str:
    return f"{org_id}/{site_id}/devices/{device_id}/logs/{at.astimezone(timezone.utc):%Y%m%dT%H%M%SZ}.log.gz"


def _expiry(ttl_s: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=ttl_s)


class S3Store:
    """S3-compatible storage (MinIO in dev, in-Kingdom S3 in production) through boto3."""

    def __init__(self, settings: CloudSettings) -> None:
        import boto3
        from botocore.config import Config

        def client(endpoint: str | None) -> Any:
            return boto3.client(
                "s3",
                endpoint_url=endpoint,
                region_name=settings.s3_region,
                aws_access_key_id=(
                    settings.s3_access_key.get_secret_value() if settings.s3_access_key else None
                ),
                aws_secret_access_key=(
                    settings.s3_secret_key.get_secret_value() if settings.s3_secret_key else None
                ),
                config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
            )

        self._bucket = settings.s3_bucket
        self._sse = settings.s3_server_side_encryption
        self._client = client(settings.s3_endpoint_url)
        # Pre-signed URLs must name the host the edge box reaches, which may differ from ours.
        self._signer = client(settings.s3_public_endpoint_url or settings.s3_endpoint_url)

    def presign_post(
        self, key: str, content_type: str, max_bytes: int, ttl_s: int
    ) -> PresignedPost:
        fields: dict[str, str] = {"Content-Type": content_type}
        conditions: list[Any] = [
            ["content-length-range", 1, max_bytes],
            {"Content-Type": content_type},
        ]
        if self._sse:
            fields["x-amz-server-side-encryption"] = self._sse
            conditions.append({"x-amz-server-side-encryption": self._sse})
        post = self._signer.generate_presigned_post(
            Bucket=self._bucket, Key=key, Fields=fields, Conditions=conditions, ExpiresIn=ttl_s
        )
        return PresignedPost(
            url=post["url"],
            fields={k: str(v) for k, v in post["fields"].items()},
            key=key,
            expires_at=_expiry(ttl_s),
            max_bytes=max_bytes,
        )

    def presign_get(self, key: str, ttl_s: int) -> str:
        url: str = self._signer.generate_presigned_url(
            "get_object", Params={"Bucket": self._bucket, "Key": key}, ExpiresIn=ttl_s
        )
        return url

    def head(self, key: str) -> StoredObject | None:
        from botocore.exceptions import ClientError

        try:
            meta = self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise
        return StoredObject(size=int(meta["ContentLength"]), content_type=meta.get("ContentType"))


@dataclass
class MemoryStore:
    """In-process store for tests and local runs without MinIO. `put` simulates the edge upload."""

    objects: dict[str, tuple[bytes, str]] = field(default_factory=dict)

    def presign_post(
        self, key: str, content_type: str, max_bytes: int, ttl_s: int
    ) -> PresignedPost:
        return PresignedPost(
            url="memory://vision-media",
            fields={"key": key, "Content-Type": content_type},
            key=key,
            expires_at=_expiry(ttl_s),
            max_bytes=max_bytes,
        )

    def presign_get(self, key: str, ttl_s: int) -> str:
        return f"memory://vision-media/{key}?expires={int(_expiry(ttl_s).timestamp())}"

    def head(self, key: str) -> StoredObject | None:
        obj = self.objects.get(key)
        return None if obj is None else StoredObject(size=len(obj[0]), content_type=obj[1])

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        self.objects[key] = (data, content_type)


def make_store(settings: CloudSettings) -> ObjectStore:
    if settings.storage_backend == "memory":
        return MemoryStore()
    return S3Store(settings)
