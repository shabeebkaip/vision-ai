"""Object storage for snapshots and clips (CLD-06 basics).

Two backends behind one interface:

- `S3Storage`  : any S3-compatible store (SeaweedFS in development, AWS S3 or an in-Kingdom provider in
                 production) through boto3 pre-signed URLs. Optional server-side encryption header.
- `LocalStorage`: files under a directory; pre-signed URLs point at this API
                 (`/storage/local/{key}`) and are HMAC-signed with an expiry. For dev and tests only.

Key layout: `{org}/{site}/{camera}/{yyyy}/{mm}/{dd}/{event_id}/{snapshot.jpg|clip.mp4}` (UTC date).
Lifecycle rules and the delete-on-request job are later parts of CLD-06.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.parse import quote, urlencode

from vision_cloud.security import hmac_sign, hmac_verify
from vision_cloud.settings import CloudSettings

MediaKind = Literal["snapshot", "clip"]
MEDIA_FILES: dict[str, tuple[str, str]] = {
    "snapshot": ("snapshot.jpg", "image/jpeg"),
    "clip": ("clip.mp4", "video/mp4"),
}


def event_media_key(
    org_id: str, site_id: str, camera_id: str, triggered_at: datetime, event_id: str, kind: str
) -> str:
    if triggered_at.tzinfo is None:
        raise ValueError("triggered_at must be timezone-aware")
    day = triggered_at.astimezone(timezone.utc)
    filename = MEDIA_FILES[kind][0]
    return f"{org_id}/{site_id}/{camera_id}/{day:%Y/%m/%d}/{event_id}/{filename}"


@dataclass(frozen=True)
class SignedRequest:
    url: str
    method: str
    expires_at: datetime
    headers: dict[str, str] = field(default_factory=dict)


class ObjectStorage(Protocol):
    def presign_put(self, key: str, content_type: str, ttl_s: int) -> SignedRequest: ...

    def presign_get(self, key: str, ttl_s: int) -> SignedRequest: ...

    def exists(self, key: str) -> bool: ...

    def size(self, key: str) -> int | None: ...

    def put_bytes(self, key: str, data: bytes, content_type: str) -> None: ...

    def read_bytes(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...


def _expiry(ttl_s: int) -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0) + timedelta(seconds=ttl_s)


class S3Storage:
    def __init__(
        self,
        bucket: str,
        *,
        endpoint_url: str | None = None,
        public_endpoint_url: str | None = None,
        region: str = "us-east-1",
        access_key: str | None = None,
        secret_key: str | None = None,
        sse: str | None = None,
        client: Any = None,
    ) -> None:
        self.bucket = bucket
        self.sse = sse

        def make(endpoint: str | None) -> Any:
            import boto3
            from botocore.config import Config

            return boto3.client(
                "s3",
                endpoint_url=endpoint,
                region_name=region,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
            )

        self._s3 = client if client is not None else make(endpoint_url)
        # Signing needs no network call; a second client only changes the host in the URL.
        self._signer = make(public_endpoint_url) if public_endpoint_url else self._s3

    def presign_put(self, key: str, content_type: str, ttl_s: int) -> SignedRequest:
        params: dict[str, Any] = {"Bucket": self.bucket, "Key": key, "ContentType": content_type}
        headers = {"Content-Type": content_type}
        if self.sse:
            params["ServerSideEncryption"] = self.sse
            headers["x-amz-server-side-encryption"] = self.sse
        url = self._signer.generate_presigned_url("put_object", Params=params, ExpiresIn=ttl_s)
        return SignedRequest(url=url, method="PUT", expires_at=_expiry(ttl_s), headers=headers)

    def presign_get(self, key: str, ttl_s: int) -> SignedRequest:
        url = self._signer.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=ttl_s
        )
        return SignedRequest(url=url, method="GET", expires_at=_expiry(ttl_s))

    def size(self, key: str) -> int | None:
        from botocore.exceptions import ClientError

        try:
            head = self._s3.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise
        return int(head.get("ContentLength", 0))

    def exists(self, key: str) -> bool:
        return self.size(key) is not None

    def put_bytes(self, key: str, data: bytes, content_type: str) -> None:
        extra: dict[str, Any] = {"ServerSideEncryption": self.sse} if self.sse else {}
        self._s3.put_object(
            Bucket=self.bucket, Key=key, Body=data, ContentType=content_type, **extra
        )

    def read_bytes(self, key: str) -> bytes:
        body = self._s3.get_object(Bucket=self.bucket, Key=key)["Body"]
        return bytes(body.read())

    def delete(self, key: str) -> None:
        self._s3.delete_object(Bucket=self.bucket, Key=key)


class LocalStorage:
    """Directory-backed storage with HMAC-signed URLs served by `api/storage_local.py`."""

    def __init__(self, root: Path, base_url: str, signing_key: str) -> None:
        self.root = root.resolve()
        self.base_url = base_url.rstrip("/")
        self._key = signing_key

    def path_for(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root not in path.parents:
            raise ValueError("key escapes the storage root")
        return path

    def _signed(self, method: str, key: str, ttl_s: int) -> tuple[str, datetime]:
        expires = _expiry(ttl_s)
        exp = str(int(expires.timestamp()))
        sig = hmac_sign(self._key, f"{method}\n{key}\n{exp}")
        query = urlencode({"expires": exp, "signature": sig})
        return f"{self.base_url}/storage/local/{quote(key)}?{query}", expires

    def verify(self, method: str, key: str, expires: str, signature: str) -> bool:
        try:
            exp = int(expires)
        except ValueError:
            return False
        if exp < int(datetime.now(timezone.utc).timestamp()):
            return False
        return hmac_verify(self._key, f"{method}\n{key}\n{exp}", signature)

    def presign_put(self, key: str, content_type: str, ttl_s: int) -> SignedRequest:
        url, expires = self._signed("PUT", key, ttl_s)
        return SignedRequest(
            url=url, method="PUT", expires_at=expires, headers={"Content-Type": content_type}
        )

    def presign_get(self, key: str, ttl_s: int) -> SignedRequest:
        url, expires = self._signed("GET", key, ttl_s)
        return SignedRequest(url=url, method="GET", expires_at=expires)

    def size(self, key: str) -> int | None:
        path = self.path_for(key)
        return path.stat().st_size if path.is_file() else None

    def exists(self, key: str) -> bool:
        return self.size(key) is not None

    def put_bytes(self, key: str, data: bytes, content_type: str) -> None:
        path = self.path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(data)
        os.replace(tmp, path)

    def read_bytes(self, key: str) -> bytes:
        return self.path_for(key).read_bytes()

    def delete(self, key: str) -> None:
        self.path_for(key).unlink(missing_ok=True)


def storage_from_settings(settings: CloudSettings) -> ObjectStorage:
    if settings.storage_backend == "local":
        return LocalStorage(
            settings.storage_local_dir,
            settings.public_base_url,
            settings.jwt_secret.get_secret_value() + ":local-storage",
        )
    return S3Storage(
        settings.storage_bucket,
        endpoint_url=settings.storage_endpoint_url,
        public_endpoint_url=settings.storage_public_endpoint_url,
        region=settings.storage_region,
        access_key=settings.storage_access_key.get_secret_value()
        if settings.storage_access_key
        else None,
        secret_key=settings.storage_secret_key.get_secret_value()
        if settings.storage_secret_key
        else None,
        sse=settings.storage_sse,
    )
