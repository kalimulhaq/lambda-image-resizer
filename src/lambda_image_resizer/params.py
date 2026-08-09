"""Parsing and validation for the service's query-string interface (?w=&h=&f=)
and for which source files are eligible to be resized at all.

Every function here returns None on invalid/missing input rather than raising —
callers treat that uniformly as "not requested," never as an error to surface.
"""

from __future__ import annotations

MIN_DIMENSION = 16
MAX_DIMENSION = 2400

# Output formats the service will convert into.
ALLOWED_OUTPUT_FORMATS = frozenset({"webp", "avif", "jpeg", "jpg", "png"})

# Source file extensions eligible for resizing. Deliberately excludes svg
# (vector — resizing it through a raster library is meaningless) and any
# non-image type.
ALLOWED_SOURCE_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "gif", "webp", "bmp"})


def parse_dimension(value: str | None) -> int | None:
    """Parse and clamp a single w= or h= value.

    Returns None if the value is missing or not a positive integer. Valid
    values are clamped into [MIN_DIMENSION, MAX_DIMENSION] rather than
    rejected, to keep compute and derivative count bounded without punishing
    a caller for an off-by-a-lot request.
    """
    if value is None:
        return None
    if not value.isdigit():
        return None
    parsed = int(value)
    if parsed <= 0:
        return None
    return max(MIN_DIMENSION, min(parsed, MAX_DIMENSION))


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
