from io import BytesIO

import boto3
import pytest
from moto import mock_aws
from PIL import Image

from lambda_image_resizer import handler as handler_module
from lambda_image_resizer.handler import handler

BUCKET = "test-bucket"


def make_event(uri: str, querystring: str = "") -> dict:
    return {
        "Records": [
            {
                "cf": {
                    "request": {
                        "uri": uri,
                        "querystring": querystring,
                        "headers": {},
                        "origin": {
                            "s3": {
                                "domainName": f"{BUCKET}.s3.amazonaws.com",
                                "customHeaders": {
                                    "x-img-bucket": [{"key": "X-Img-Bucket", "value": BUCKET}],
                                    "x-img-resized-prefix": [
                                        {"key": "X-Img-Resized-Prefix", "value": "resized"}
                                    ],
                                    "x-img-quality": [{"key": "X-Img-Quality", "value": "82"}],
                                },
                            }
                        },
                    }
                }
            }
        ]
    }


def make_image_bytes(w: int = 1000, h: int = 500, fmt: str = "PNG") -> bytes:
    img = Image.new("RGB", (w, h), color=(200, 100, 50))
    buf = BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


@pytest.fixture
def s3_bucket():
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield client


class TestHandlerDerivativeMissing:
    def test_computes_and_uploads_derivative_then_rewrites_uri(self, s3_bucket):
        s3_bucket.put_object(
            Bucket=BUCKET, Key="uploads/pro-01.png", Body=make_image_bytes(1000, 500)
        )
        event = make_event("/uploads/pro-01.png", "w=500&h=333&f=webp")

        result = handler(event, None)

        assert result["uri"] == "/resized/w500h333/webp/uploads/pro-01.png"
        derivative = s3_bucket.get_object(
            Bucket=BUCKET, Key="resized/w500h333/webp/uploads/pro-01.png"
        )
        assert derivative["ContentType"] == "image/webp"
        out_img = Image.open(BytesIO(derivative["Body"].read()))
        assert out_img.size[0] <= 500
        assert out_img.size[1] <= 333


class TestHandlerDerivativeExists:
    def test_rewrites_uri_without_recomputing(self, s3_bucket):
        # Only the derivative exists, not the "original" — proves the
        # handler never even tried to fetch/resize when it already had a hit.
        s3_bucket.put_object(
            Bucket=BUCKET,
            Key="resized/w500h333/webp/uploads/pro-01.png",
            Body=b"already-resized-bytes",
            ContentType="image/webp",
        )
        event = make_event("/uploads/pro-01.png", "w=500&h=333&f=webp")

        result = handler(event, None)

        assert result["uri"] == "/resized/w500h333/webp/uploads/pro-01.png"


class TestHandlerPassThrough:
    def test_no_transform_params_passes_through_untouched(self, s3_bucket):
        event = make_event("/uploads/pro-01.png", "")
        result = handler(event, None)
        assert result["uri"] == "/uploads/pro-01.png"

    def test_disallowed_source_extension_passes_through_without_s3_access(self, s3_bucket):
        # No objects seeded at all — if the handler touched S3 for a
        # nonexistent key it would still just 404/pass-through, but this
        # also proves it doesn't blow up on an svg it should never touch.
        event = make_event("/uploads/logo.svg", "w=500")
        result = handler(event, None)
        assert result["uri"] == "/uploads/logo.svg"

    def test_missing_config_headers_passes_through(self, s3_bucket):
        event = make_event("/uploads/pro-01.png", "w=500")
        del event["Records"][0]["cf"]["request"]["origin"]["s3"]["customHeaders"]["x-img-bucket"]
        result = handler(event, None)
        assert result["uri"] == "/uploads/pro-01.png"

    def test_original_not_in_bucket_passes_through(self, s3_bucket):
        event = make_event("/uploads/does-not-exist.png", "w=500")
        result = handler(event, None)
        assert result["uri"] == "/uploads/does-not-exist.png"

    def test_corrupt_image_bytes_passes_through(self, s3_bucket):
        s3_bucket.put_object(Bucket=BUCKET, Key="uploads/broken.png", Body=b"not-a-real-image")
        event = make_event("/uploads/broken.png", "w=500")
        result = handler(event, None)
        assert result["uri"] == "/uploads/broken.png"

    def test_invalid_width_passes_through(self, s3_bucket):
        s3_bucket.put_object(Bucket=BUCKET, Key="uploads/pro-01.png", Body=make_image_bytes())
        event = make_event("/uploads/pro-01.png", "w=notanumber")
        result = handler(event, None)
        assert result["uri"] == "/uploads/pro-01.png"

    def test_unsupported_format_passes_through(self, s3_bucket):
        s3_bucket.put_object(Bucket=BUCKET, Key="uploads/pro-01.png", Body=make_image_bytes())
        event = make_event("/uploads/pro-01.png", "f=bmp")
        result = handler(event, None)
        assert result["uri"] == "/uploads/pro-01.png"

    def test_every_failure_path_returns_a_request_never_a_response(self, s3_bucket):
        cases = [
            ("/uploads/logo.svg", "w=500"),
            ("/uploads/does-not-exist.png", "w=500"),
            ("/uploads/pro-01.png", "w=notanumber"),
        ]
        for uri, qs in cases:
            result = handler(make_event(uri, qs), None)
            assert "uri" in result
            assert "statusCode" not in result


class TestHandlerWidthOnlyAndHeightOnly:
    def test_width_only(self, s3_bucket):
        s3_bucket.put_object(
            Bucket=BUCKET, Key="uploads/pro-01.png", Body=make_image_bytes(1000, 500)
        )
        result = handler(make_event("/uploads/pro-01.png", "w=400"), None)
        assert result["uri"] == "/resized/w400/orig/uploads/pro-01.png"
        derivative = s3_bucket.get_object(Bucket=BUCKET, Key="resized/w400/orig/uploads/pro-01.png")
        out_img = Image.open(BytesIO(derivative["Body"].read()))
        assert out_img.size == (400, 200)

    def test_height_only(self, s3_bucket):
        s3_bucket.put_object(
            Bucket=BUCKET, Key="uploads/pro-01.png", Body=make_image_bytes(1000, 500)
        )
        result = handler(make_event("/uploads/pro-01.png", "h=250"), None)
        assert result["uri"] == "/resized/h250/orig/uploads/pro-01.png"


class TestHandlerResilience:
    """Exercises the two top-level try/except fallbacks directly, proving the
    'never generate an error response' guarantee holds even for genuinely
    unexpected failures, not just anticipated validation errors.
    """

    def test_unexpected_exception_in_process_falls_back_to_original_request(
        self, s3_bucket, monkeypatch
    ):
        s3_bucket.put_object(Bucket=BUCKET, Key="uploads/pro-01.png", Body=make_image_bytes())

        def boom(*_args, **_kwargs):
            raise RuntimeError("simulated unexpected failure")

        monkeypatch.setattr(handler_module.storage, "derivative_exists", boom)

        event = make_event("/uploads/pro-01.png", "w=400")
        result = handler(event, None)

        assert result["uri"] == "/uploads/pro-01.png"
        assert "statusCode" not in result

    def test_upload_failure_falls_back_to_original_request(self, s3_bucket, monkeypatch):
        s3_bucket.put_object(Bucket=BUCKET, Key="uploads/pro-01.png", Body=make_image_bytes())

        def boom(*_args, **_kwargs):
            raise RuntimeError("simulated S3 write failure")

        monkeypatch.setattr(handler_module.storage, "put_derivative", boom)

        event = make_event("/uploads/pro-01.png", "w=400")
        result = handler(event, None)

        assert result["uri"] == "/uploads/pro-01.png"


class TestParseQuerystringEdgeCases:
    def test_malformed_pair_without_key_is_ignored(self):
        # e.g. a stray leading '&' or '=value' with no key name
        result = handler_module._parse_querystring("=orphan&w=400")
        assert result == {"w": "400"}
        assert "" not in result
