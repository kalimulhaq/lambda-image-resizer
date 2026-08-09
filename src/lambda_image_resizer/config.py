"""Per-distribution configuration.

Lambda@Edge functions cannot use environment variables, so configuration is
instead passed via CloudFront origin custom headers, set once per
distribution/origin at infrastructure-config time. This is what makes a
single deployed function reusable across unrelated buckets/projects: the
code never hardcodes a bucket name.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

BUCKET_HEADER = "x-img-bucket"
RESIZED_PREFIX_HEADER = "x-img-resized-prefix"
QUALITY_HEADER = "x-img-quality"

DEFAULT_QUALITY = 82


class ConfigError(Exception):
    """Raised when required origin custom headers are missing or malformed."""


@dataclass(frozen=True)
class OriginConfig:
    bucket: str
    resized_prefix: str
    quality: int

    @classmethod
    def from_custom_headers(cls, custom_headers: dict[str, Any]) -> OriginConfig:
        """Parse a CloudFront `origin.s3.customHeaders`-shaped dict:
        {'x-img-bucket': [{'key': 'X-Img-Bucket', 'value': 'my-bucket'}], ...}
        """
        bucket = _header_value(custom_headers, BUCKET_HEADER)
        if not bucket:
            raise ConfigError(f"Missing required origin header: {BUCKET_HEADER}")

        resized_prefix = _header_value(custom_headers, RESIZED_PREFIX_HEADER) or "resized"

        quality_raw = _header_value(custom_headers, QUALITY_HEADER)
        quality = DEFAULT_QUALITY
        if quality_raw is not None:
            try:
                quality = int(quality_raw)
            except ValueError as exc:
                raise ConfigError(f"Invalid {QUALITY_HEADER}: {quality_raw!r}") from exc
            if not (1 <= quality <= 100):
                raise ConfigError(f"{QUALITY_HEADER} must be 1-100, got {quality}")

        return cls(bucket=bucket, resized_prefix=resized_prefix, quality=quality)


def _header_value(custom_headers: dict[str, Any], name: str) -> str | None:
    entries = custom_headers.get(name)
    if not entries:
        return None
    try:
        value = entries[0]["value"]
    except (IndexError, KeyError, TypeError):
        return None
    return str(value) if value else None
