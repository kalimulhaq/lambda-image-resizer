"""Deterministic S3 key construction for resized/converted derivatives."""

from __future__ import annotations


def derivative_key(
    original_key: str,
    prefix: str,
    width: int | None,
    height: int | None,
    fmt: str | None,
) -> str:
    """Build the S3 key a given (original_key, width, height, fmt) combination
    is stored/looked-up under.

    Deterministic and collision-free across every combination of the three
    optional transform inputs:
        both dims   -> {prefix}/w500h333/{fmt_token}/{original_key}
        width only  -> {prefix}/w500/{fmt_token}/{original_key}
        height only -> {prefix}/h333/{fmt_token}/{original_key}
        neither dim -> {prefix}/orig/{fmt_token}/{original_key}
    fmt_token is the requested format, or 'orig' if no format conversion
    was requested (dimension-only resize, source format kept).
    """
    dim_token = ""
    if width is not None:
        dim_token += f"w{width}"
    if height is not None:
        dim_token += f"h{height}"
    if not dim_token:
        dim_token = "orig"

    fmt_token = fmt if fmt is not None else "orig"

    clean_prefix = prefix.strip("/")
    clean_key = original_key.lstrip("/")
    return f"{clean_prefix}/{dim_token}/{fmt_token}/{clean_key}"
