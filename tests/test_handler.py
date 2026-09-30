from io import BytesIO

import boto3
import pytest
from moto import mock_aws
from PIL import Image

from lambda_image_resizer import handler as handler_module
from lambda_image_resizer.handler import handler

BUCKET = "test-bucket"


def make_event(uri: str, querystring: str = "", extra_headers: dict | None = None) -> dict:
    custom_headers = {
        "x-img-bucket": [{"key": "X-Img-Bucket", "value": BUCKET}],
        "x-img-resized-prefix": [{"key": "X-Img-Resized-Prefix", "value": "resized"}],
        "x-img-quality": [{"key": "X-Img-Quality", "value": "82"}],
    }
    for name, value in (extra_headers or {}).items():
        custom_headers[name.lower()] = [{"key": name, "value": value}]
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
                                "region": "us-east-1",
                                "customHeaders": custom_headers,
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


class TestHandlerHardening:
    def test_percent_encoded_uri_is_decoded_for_s3_and_reencoded(self, s3_bucket):
        s3_bucket.put_object(
            Bucket=BUCKET, Key="uploads/my photo é.png", Body=make_image_bytes(1000, 500)
        )
        result = handler(make_event("/uploads/my%20photo%20%C3%A9.png", "w=400"), None)
        assert result["uri"] == "/resized/w400/orig/uploads/my%20photo%20%C3%A9.png"
        s3_bucket.head_object(Bucket=BUCKET, Key="resized/w400/orig/uploads/my photo é.png")

    def test_query_string_cleared_after_rewrite(self, s3_bucket):
        s3_bucket.put_object(Bucket=BUCKET, Key="uploads/pro-01.png", Body=make_image_bytes())
        result = handler(make_event("/uploads/pro-01.png", "w=400&f=webp"), None)
        assert result["querystring"] == ""

    def test_derivative_has_cache_control(self, s3_bucket):
        s3_bucket.put_object(Bucket=BUCKET, Key="uploads/pro-01.png", Body=make_image_bytes())
        handler(make_event("/uploads/pro-01.png", "w=400"), None)
        head = s3_bucket.head_object(Bucket=BUCKET, Key="resized/w400/orig/uploads/pro-01.png")
        assert head["CacheControl"] == "public, max-age=31536000, immutable"

    def test_existing_derivative_is_never_resized_again(self, s3_bucket):
        key = "resized/w400/orig/uploads/pro-01.png"
        s3_bucket.put_object(Bucket=BUCKET, Key=key, Body=make_image_bytes(400, 200))
        result = handler(make_event("/" + key, "w=100"), None)
        assert result["uri"] == "/" + key
        assert result["querystring"] == "w=100"

    def test_allowed_sizes_snap_the_derivative_key(self, s3_bucket):
        s3_bucket.put_object(Bucket=BUCKET, Key="uploads/pro-01.png", Body=make_image_bytes())
        event = make_event("/uploads/pro-01.png", "w=500", {"X-Img-Allowed-Sizes": "320,640,1280"})
        assert handler(event, None)["uri"] == "/resized/w640/orig/uploads/pro-01.png"

    def test_oversized_original_passes_through(self, s3_bucket, monkeypatch):
        monkeypatch.setattr(handler_module, "MAX_SOURCE_BYTES", 10)
        s3_bucket.put_object(Bucket=BUCKET, Key="uploads/pro-01.png", Body=make_image_bytes())
        result = handler(make_event("/uploads/pro-01.png", "w=400"), None)
        assert result["uri"] == "/uploads/pro-01.png"

    def test_bucket_region_passed_to_storage(self, s3_bucket, monkeypatch):
        seen = []

        def fake_exists(bucket, key, region=None):
            seen.append(region)
            return True

        monkeypatch.setattr(handler_module.storage, "derivative_exists", fake_exists)
        handler(make_event("/uploads/pro-01.png", "w=400"), None)
        assert seen == ["us-east-1"]

    def test_url_encoded_query_value(self, s3_bucket):
        s3_bucket.put_object(Bucket=BUCKET, Key="uploads/pro-01.png", Body=make_image_bytes())
        result = handler(make_event("/uploads/pro-01.png", "f=%57EBP"), None)
        assert result["uri"] == "/resized/orig/webp/uploads/pro-01.png"


class TestHandlerLegacyDimensionParam:
    def test_d_param_maps_to_width_and_height(self, s3_bucket):
        s3_bucket.put_object(
            Bucket=BUCKET, Key="uploads/pro-01.jpg", Body=make_image_bytes(2000, 1000, "JPEG")
        )
        result = handler(make_event("/uploads/pro-01.jpg", "f=webp&d=1000x666"), None)
        assert result["uri"] == "/resized/w1000h666/webp/uploads/pro-01.jpg"
        derivative = s3_bucket.get_object(
            Bucket=BUCKET, Key="resized/w1000h666/webp/uploads/pro-01.jpg"
        )
        assert Image.open(BytesIO(derivative["Body"].read())).size == (1000, 500)

    def test_d_param_width_or_height_only(self, s3_bucket):
        s3_bucket.put_object(Bucket=BUCKET, Key="uploads/pro-01.png", Body=make_image_bytes())
        assert handler(make_event("/uploads/pro-01.png", "d=400x"), None)["uri"] == (
            "/resized/w400/orig/uploads/pro-01.png"
        )
        assert handler(make_event("/uploads/pro-01.png", "d=X250"), None)["uri"] == (
            "/resized/h250/orig/uploads/pro-01.png"
        )

    def test_explicit_w_h_take_precedence_over_d(self, s3_bucket):
        s3_bucket.put_object(Bucket=BUCKET, Key="uploads/pro-01.png", Body=make_image_bytes())
        result = handler(make_event("/uploads/pro-01.png", "w=300&d=1000x666"), None)
        assert result["uri"] == "/resized/w300/orig/uploads/pro-01.png"

    def test_malformed_d_passes_through(self, s3_bucket):
        s3_bucket.put_object(Bucket=BUCKET, Key="uploads/pro-01.png", Body=make_image_bytes())
        result = handler(make_event("/uploads/pro-01.png", "d=bogus"), None)
        assert result["uri"] == "/uploads/pro-01.png"
