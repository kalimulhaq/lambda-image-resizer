"""Parsing and validation for the service's query-string interface (?w=&h=&f=)
and for which source files are eligible to be resized at all.

Every function here returns None on invalid/missing input rather than raising —
callers treat that uniformly as "not requested," never as an error to surface.
"""

from __future__ import annotations

MIN_DIMENSION = 16
# Default cap on w/h; overridable per distribution via X-Img-Max-Dimension,
# but never above HARD_MAX_DIMENSION. Every distinct value is a separate
# derivative (the key is built before the source size is known), so an
# unbounded cap would let anyone mint unlimited full-size re-encodes.
DEFAULT_MAX_DIMENSION = 4096
HARD_MAX_DIMENSION = 8192

# Output formats the service will convert into.
ALLOWED_OUTPUT_FORMATS = frozenset({"webp", "avif", "jpeg", "jpg", "png"})

# Source file extensions eligible for resizing. Deliberately excludes svg
# (vector — resizing it through a raster library is meaningless) and any
# non-image type.
ALLOWED_SOURCE_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "gif", "webp", "bmp"})


def parse_dimension(
    value: str | None,
    max_dimension: int = DEFAULT_MAX_DIMENSION,
    allowed_sizes: tuple[int, ...] | None = None,
) -> int | None:
    """Parse and clamp a single w= or h= value.

    Returns None if the value is missing or not a positive integer. Valid
    values are clamped into [MIN_DIMENSION, max_dimension] rather than
    rejected, to keep compute and derivative count bounded without punishing
    a caller for an off-by-a-lot request.

    If `allowed_sizes` (sorted ascending) is given, the clamped value is then
    snapped up to the nearest allowed size (or the largest one), so only
    len(allowed_sizes) distinct derivatives per dimension can ever exist.
    """
    if value is None:
        return None
    # isascii() rules out Unicode digits like '²' that isdigit() accepts but
    # int() rejects.
    if not value.isascii() or not value.isdigit():
        return None
    digits = value.lstrip("0")
    if not digits:
        return None
    # Don't int() arbitrarily long strings; anything this long is over the cap.
    parsed = int(digits) if len(digits) <= 9 else max_dimension
    clamped = max(MIN_DIMENSION, min(parsed, max_dimension))
    if allowed_sizes:
        return next((size for size in allowed_sizes if size >= clamped), allowed_sizes[-1])
    return clamped


def parse_format(value: str | None) -> str | None:
    """Parse and validate an f= value against the output allow-list."""
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized not in ALLOWED_OUTPUT_FORMATS:
        return None
    return normalized


def source_extension(key: str) -> str:
    """Return the lowercased extension (no dot) of an S3 key, or '' if none."""
    dot_index = key.rfind(".")
    slash_index = key.rfind("/")
    if dot_index == -1 or dot_index < slash_index:
        return ""
    return key[dot_index + 1 :].lower()


def is_resizable_source(key: str) -> bool:
    """Whether the original file at this key is eligible for resize processing."""
    return source_extension(key) in ALLOWED_SOURCE_EXTENSIONS
