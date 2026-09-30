"""Lambda@Edge origin-request entrypoint.

Thin orchestration only — all real logic lives in the other modules. This
function never returns a generated error response: every failure mode
(missing/bad config, ineligible source type, invalid query params, a corrupt
or oversized image, an S3 error) results in passing the original CloudFront
request through unchanged, so a resize failure never breaks the page.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote, unquote

from PIL import UnidentifiedImageError

from . import storage
from .config import ConfigError, OriginConfig
from .keys import derivative_key, is_derivative_key
from .params import is_resizable_source, parse_dimension, parse_format
from .resize import ImageTooLarge, convert_and_save, fit_inside_no_upscale, load_image

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Originals larger than this are served as-is rather than downloaded.
MAX_SOURCE_BYTES = 25 * 1024 * 1024

_CONTENT_TYPES = {
    "webp": "image/webp",
    "avif": "image/avif",
    "jpeg": "image/jpeg",
    "jpg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "bmp": "image/bmp",
}


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    request: dict[str, Any] = event["Records"][0]["cf"]["request"]

    try:
        return _process(request)
    except Exception:  # noqa: BLE001 - deliberate: never break the page
        logger.exception("lambda-image-resizer: unhandled error, passing request through")
        return request


def _process(request: dict[str, Any]) -> dict[str, Any]:
    # CloudFront hands us the URI percent-encoded; S3 keys are not.
    original_key = unquote(request["uri"]).lstrip("/")

    if not is_resizable_source(original_key):
        return request

    try:
        s3_origin = request["origin"]["s3"]
        config = OriginConfig.from_custom_headers(s3_origin["customHeaders"])
    except (ConfigError, KeyError):
        logger.warning("lambda-image-resizer: missing/invalid origin config, passing through")
        return request

    # Never treat our own output as a source — that would let callers chain
    # derivatives-of-derivatives indefinitely.
    if is_derivative_key(original_key, config.resized_prefix):
        return request

    query_params = _parse_querystring(request.get("querystring", ""))
    width_raw, height_raw = query_params.get("w"), query_params.get("h")
    if width_raw is None and height_raw is None and "d" in query_params:
        # Legacy `d=WxH` form; explicit w/h take precedence.
        width_raw, _, height_raw = query_params["d"].lower().partition("x")
    width = parse_dimension(width_raw, config.max_dimension, config.allowed_sizes)
    height = parse_dimension(height_raw, config.max_dimension, config.allowed_sizes)
    fmt = parse_format(query_params.get("f"))

    if width is None and height is None and fmt is None:
        return request

    region = s3_origin.get("region")
    dest_key = derivative_key(original_key, config.resized_prefix, width, height, fmt)

    if storage.derivative_exists(config.bucket, dest_key, region):
        return _rewrite(request, dest_key)

    try:
        original_bytes, _content_type = storage.get_original(
            config.bucket, original_key, MAX_SOURCE_BYTES, region
        )
        image, source_format = load_image(original_bytes, width, height)
    except UnidentifiedImageError:
        logger.warning(
            "lambda-image-resizer: unreadable image at %s, passing through", original_key
        )
        return request
    except (ImageTooLarge, storage.ObjectTooLarge) as exc:
        logger.warning("lambda-image-resizer: %s, passing through", exc)
        return request
    except Exception:
        logger.warning(
            "lambda-image-resizer: could not fetch/open %s, passing through", original_key
        )
        return request

    try:
        resized = fit_inside_no_upscale(image, width, height)
        out_bytes, out_fmt = convert_and_save(resized, fmt, config.quality, source_format)
        content_type = _CONTENT_TYPES.get(out_fmt, "application/octet-stream")
        storage.put_derivative(
            config.bucket, dest_key, out_bytes, content_type, config.cache_control, region
        )
    except Exception:
        logger.exception(
            "lambda-image-resizer: resize/upload failed for %s, passing through", original_key
        )
        return request

    return _rewrite(request, dest_key)


def _rewrite(request: dict[str, Any], dest_key: str) -> dict[str, Any]:
    """Point the request at `dest_key`. The query string is dropped: it's
    already encoded in the key and S3 has no use for it.
    """
    request["uri"] = "/" + quote(dest_key)
    request["querystring"] = ""
    return request


def _parse_querystring(querystring: str) -> dict[str, str]:
    params: dict[str, str] = {}
    if not querystring:
        return params
    for pair in querystring.split("&"):
        if not pair:
            continue
        key, _, value = pair.partition("=")
        if key:
            params[key] = unquote(value)
    return params
