"""Google Cloud Storage helpers for media uploads and signed URLs."""

from __future__ import annotations

import logging
import mimetypes
import os
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Optional

try:
    from google.cloud import storage as _storage
except ImportError:
    _storage = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)


@dataclass
class GcsConfig:
    bucket: str
    public: bool
    signed_url_ttl_seconds: int


def _get_config() -> GcsConfig | None:
    bucket = os.getenv("GCS_BUCKET", "").strip()
    if not bucket:
        return None

    public = os.getenv("GCS_PUBLIC", "false").strip().lower() in {"1", "true", "yes", "on"}
    ttl = int(os.getenv("GCS_SIGNED_URL_TTL_SECONDS", "3600"))
    return GcsConfig(bucket=bucket, public=public, signed_url_ttl_seconds=ttl)


def gcs_enabled() -> bool:
    return _get_config() is not None and _storage is not None


def _client() -> Any:
    if _storage is None:
        raise RuntimeError("google-cloud-storage package is not installed")
    return _storage.Client()


def _guess_content_type(path: str) -> str | None:
    ctype, _ = mimetypes.guess_type(path)
    return ctype


def upload_file_to_gcs(local_path: str, blob_path: str, content_type: str | None = None) -> str:
    cfg = _get_config()
    if not cfg:
        raise RuntimeError("GCS_BUCKET not configured")

    local = Path(local_path)
    if not local.exists():
        raise FileNotFoundError(local_path)

    client = _client()
    bucket = client.bucket(cfg.bucket)
    blob = bucket.blob(blob_path)

    ctype = content_type or _guess_content_type(local_path)
    blob.upload_from_filename(local_path, content_type=ctype)

    if cfg.public:
        try:
            blob.make_public()
        except Exception as exc:  # pragma: no cover - depends on bucket ACL mode
            logger.warning("Failed to set object public; relying on bucket IAM: %s", exc)

    return f"gs://{cfg.bucket}/{blob_path}"


def _parse_gs_url(url: str) -> tuple[str, str] | None:
    if not url.startswith("gs://"):
        return None
    rest = url[5:]
    parts = rest.split("/", 1)
    if len(parts) != 2:
        return None
    return parts[0], parts[1]


def resolve_media_url(url: str) -> str:
    """Return a public or signed HTTPS URL if input is gs://. Otherwise return original."""
    cfg = _get_config()
    if not cfg:
        return url

    parsed = _parse_gs_url(url)
    if not parsed:
        return url

    bucket_name, blob_name = parsed
    if cfg.public:
        return f"https://storage.googleapis.com/{bucket_name}/{blob_name}"

    client = _client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    return blob.generate_signed_url(
        version="v4",
        expiration=timedelta(seconds=cfg.signed_url_ttl_seconds),
        method="GET",
    )
