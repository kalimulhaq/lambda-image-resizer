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

from .params import DEFAULT_MAX_DIMENSION, HARD_MAX_DIMENSION, MIN_DIMENSION

BUCKET_HEADER = "x-img-bucket"
RESIZED_PREFIX_HEADER = "x-img-resized-prefix"
QUALITY_HEADER = "x-img-quality"
MAX_DIMENSION_HEADER = "x-img-max-dimension"
ALLOWED_SIZES_HEADER = "x-img-allowed-sizes"
CACHE_CONTROL_HEADER = "x-img-cache-control"

DEFAULT_QUALITY = 82

# Derivatives are keyed by (key, w, h, f) only and never change once written,
# so browsers and CloudFront may keep them for as long as they like.
DEFAULT_CACHE_CONTROL = "public, max-age=31536000, immutable"


class ConfigError(Exception):
    """Raised when required origin custom headers are missing or malformed."""


@dataclass(frozen=True)
class OriginConfig:
    bucket: str
    resized_prefix: str
    quality: int
    max_dimension: int = DEFAULT_MAX_DIMENSION
    allowed_sizes: tuple[int, ...] | None = None
    cache_control: str = DEFAULT_CACHE_CONTROL

    @classmethod
    def from_custom_headers(cls, custom_headers: dict[str, Any]) -> OriginConfig:
        """Parse a CloudFront `origin.s3.customHeaders`-shaped dict:
        {'x-img-bucket': [{'key': 'X-Img-Bucket', 'value': 'my-bucket'}], ...}
        """
        bucket = _header_value(custom_headers, BUCKET_HEADER)
        if not bucket:
            raise ConfigError(f"Missing required origin header: {BUCKET_HEADER}")

        resized_prefix = (_header_value(custom_headers, RESIZED_PREFIX_HEADER) or "resized").strip(
            "/"
        )
        if not resized_prefix:
            raise ConfigError(f"{RESIZED_PREFIX_HEADER} must not be empty")

        quality = _int_header(custom_headers, QUALITY_HEADER, DEFAULT_QUALITY, 1, 100)
        max_dimension = _int_header(
            custom_headers,
            MAX_DIMENSION_HEADER,
            DEFAULT_MAX_DIMENSION,
            MIN_DIMENSION,
            HARD_MAX_DIMENSION,
        )
        allowed_sizes = _allowed_sizes(custom_headers, max_dimension)
        cache_control = _header_value(custom_headers, CACHE_CONTROL_HEADER) or (
            DEFAULT_CACHE_CONTROL
        )

        return cls(
            bucket=bucket,
            resized_prefix=resized_prefix,
            quality=quality,
            max_dimension=max_dimension,
            allowed_sizes=allowed_sizes,
            cache_control=cache_control,
        )


def _header_value(custom_headers: dict[str, Any], name: str) -> str | None:
    entries = custom_headers.get(name)
    if not entries:
        return None
    try:
        value = entries[0]["value"]
    except (IndexError, KeyError, TypeError):
        return None
    return str(value).strip() if value else None


def _int_header(
    custom_headers: dict[str, Any], name: str, default: int, low: int, high: int
) -> int:
    raw = _header_value(custom_headers, name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"Invalid {name}: {raw!r}") from exc
    if not (low <= value <= high):
        raise ConfigError(f"{name} must be {low}-{high}, got {value}")
    return value


def _allowed_sizes(custom_headers: dict[str, Any], max_dimension: int) -> tuple[int, ...] | None:
    """Parse e.g. '320,640,1280' into a sorted, de-duplicated tuple."""
    raw = _header_value(custom_headers, ALLOWED_SIZES_HEADER)
    if raw is None:
        return None
    try:
        sizes = {int(part) for part in raw.split(",") if part.strip()}
    except ValueError as exc:
        raise ConfigError(f"Invalid {ALLOWED_SIZES_HEADER}: {raw!r}") from exc
    if not sizes:
        return None
    if any(not (MIN_DIMENSION <= size <= max_dimension) for size in sizes):
        raise ConfigError(
            f"{ALLOWED_SIZES_HEADER} values must be {MIN_DIMENSION}-{max_dimension}, got {raw!r}"
        )
    return tuple(sorted(sizes))
