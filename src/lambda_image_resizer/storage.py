"""Thin S3 wrapper isolating all boto3 calls, so handler.py stays free of
AWS SDK details and this module is what tests mock (via moto).
"""

from __future__ import annotations

from typing import Any

import boto3
from botocore.exceptions import ClientError

_client: Any = None


def _s3() -> Any:
    global _client
    if _client is None:
        _client = boto3.client("s3")
    return _client


def derivative_exists(bucket: str, key: str) -> bool:
    try:
        _s3().head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code in ("404", "NoSuchKey"):
            return False
        raise


def get_original(bucket: str, key: str) -> tuple[bytes, str | None]:
    """Returns (bytes, content_type). Raises ClientError with code
    'NoSuchKey' if the object doesn't exist — callers treat that as a
    pass-through condition, not an error to propagate.
    """
    response = _s3().get_object(Bucket=bucket, Key=key)
    body = response["Body"].read()
    content_type = response.get("ContentType")
    return body, content_type


def put_derivative(bucket: str, key: str, body: bytes, content_type: str) -> None:
    _s3().put_object(Bucket=bucket, Key=key, Body=body, ContentType=content_type)
