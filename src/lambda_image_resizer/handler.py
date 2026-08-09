"""Lambda@Edge origin-request entrypoint.

Thin orchestration only — all real logic lives in the other modules. This
function never returns a generated error response: every failure mode
(missing/bad config, ineligible source type, invalid query params, a corrupt
image, an S3 error) results in passing the original CloudFront request
through unchanged, so a resize failure never breaks the page.
"""

from __future__ import annotations

import logging
from io import BytesIO
from typing import Any

from PIL import Image, UnidentifiedImageError

from . import storage
from .config import ConfigError, OriginConfig
from .keys import derivative_key
from .params import is_resizable_source, parse_dimension, parse_format
from .resize import convert_and_save, fit_inside_no_upscale

logger = logging.getLogger()
logger.setLevel(logging.INFO)

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
    original_key = request["uri"].lstrip("/")

    if not is_resizable_source(original_key):
        return request

    try:
        custom_headers = request["origin"]["s3"]["customHeaders"]
        config = OriginConfig.from_custom_headers(custom_headers)
    except (ConfigError, KeyError):
        logger.warning("lambda-image-resizer: missing/invalid origin config, passing through")
        return request

    query_params = _parse_querystring(request.get("querystring", ""))
    width = parse_dimension(query_params.get("w"))
    height = parse_dimension(query_params.get("h"))
    fmt = parse_format(query_params.get("f"))

    if width is None and height is None and fmt is None:
        return request

    dest_key = derivative_key(original_key, config.resized_prefix, width, height, fmt)

    if storage.derivative_exists(config.bucket, dest_key):
        request["uri"] = "/" + dest_key
        return request

    try:
        original_bytes, _content_type = storage.get_original(config.bucket, original_key)
        image = Image.open(BytesIO(original_bytes))
        image.load()
    except UnidentifiedImageError:
        logger.warning(
            "lambda-image-resizer: unreadable image at %s, passing through", original_key
        )
        return request
    except Exception:
        logger.warning(
            "lambda-image-resizer: could not fetch/open %s, passing through", original_key
        )
        return request

    try:
        resized = fit_inside_no_upscale(image, width, height)
        out_bytes, out_fmt = convert_and_save(resized, fmt, config.quality)
        content_type = _CONTENT_TYPES.get(out_fmt, "application/octet-stream")
        storage.put_derivative(config.bucket, dest_key, out_bytes, content_type)
    except Exception:
        logger.exception(
            "lambda-image-resizer: resize/upload failed for %s, passing through", original_key
        )
        return request

    request["uri"] = "/" + dest_key
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
            params[key] = value
    return params
