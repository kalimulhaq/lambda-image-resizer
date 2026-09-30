"""Thin S3 wrapper isolating all boto3 calls, so handler.py stays free of
AWS SDK details and this module is what tests mock (via moto).
"""

from __future__ import annotations

from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

# Lambda@Edge origin-request functions get at most 30s in total; fail fast on
# a stuck connection instead of burning the whole budget on one S3 call.
_CLIENT_CONFIG = Config(
    connect_timeout=2,
    read_timeout=10,
    retries={"max_attempts": 3, "mode": "standard"},
    tcp_keepalive=True,
)

# One client per bucket region, reused across warm invocations. The function
# runs in whichever region hosts the serving edge cache, so talking to the
# bucket's own region directly avoids a cross-region redirect round-trip.
_clients: dict[str | None, Any] = {}


class ObjectTooLarge(Exception):
    """Raised when an original exceeds the download size limit."""


def _s3(region: str | None = None) -> Any:
    client = _clients.get(region)
    if client is None:
        client = boto3.client("s3", region_name=region, config=_CLIENT_CONFIG)
        _clients[region] = client
    return client


def derivative_exists(bucket: str, key: str, region: str | None = None) -> bool:
    try:
        _s3(region).head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code in ("404", "NoSuchKey"):
            return False
        raise


def get_original(
    bucket: str, key: str, max_bytes: int, region: str | None = None
) -> tuple[bytes, str | None]:
    """Returns (bytes, content_type). Raises ClientError with code
    'NoSuchKey' if the object doesn't exist, or ObjectTooLarge if it is
    bigger than `max_bytes` (checked before the body is downloaded) —
    callers treat both as pass-through conditions.
    """
    response = _s3(region).get_object(Bucket=bucket, Key=key)
    body = response["Body"]
    if response.get("ContentLength", 0) > max_bytes:
        body.close()
        raise ObjectTooLarge(f"{key} is {response['ContentLength']} bytes (max {max_bytes})")
    data = body.read()
    return data, response.get("ContentType")


def put_derivative(
    bucket: str,
    key: str,
    body: bytes,
    content_type: str,
    cache_control: str,
    region: str | None = None,
) -> None:
    _s3(region).put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType=content_type,
        CacheControl=cache_control,
    )
