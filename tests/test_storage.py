from types import SimpleNamespace

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from lambda_image_resizer import storage

BUCKET = "test-storage-bucket"


@pytest.fixture
def s3_bucket():
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield client


class TestDerivativeExists:
    def test_true_when_present(self, s3_bucket):
        s3_bucket.put_object(Bucket=BUCKET, Key="x.png", Body=b"data")
        assert storage.derivative_exists(BUCKET, "x.png") is True

    def test_false_when_missing(self, s3_bucket):
        assert storage.derivative_exists(BUCKET, "missing.png") is False

    def test_non_404_client_errors_propagate(self, s3_bucket, monkeypatch):
        def boom(*_args, **_kwargs):
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "nope"}}, "HeadObject")

        monkeypatch.setattr(storage, "_s3", lambda _region=None: SimpleNamespace(head_object=boom))

        with pytest.raises(ClientError):
            storage.derivative_exists(BUCKET, "x.png")


class TestGetOriginal:
    def test_returns_bytes_and_content_type(self, s3_bucket):
        s3_bucket.put_object(Bucket=BUCKET, Key="x.png", Body=b"data", ContentType="image/png")
        assert storage.get_original(BUCKET, "x.png", max_bytes=100) == (b"data", "image/png")

    def test_too_large_raises_before_reading(self, s3_bucket):
        s3_bucket.put_object(Bucket=BUCKET, Key="big.png", Body=b"x" * 101)
        with pytest.raises(storage.ObjectTooLarge):
            storage.get_original(BUCKET, "big.png", max_bytes=100)


class TestPutDerivative:
    def test_sets_content_type_and_cache_control(self, s3_bucket):
        storage.put_derivative(BUCKET, "d.webp", b"data", "image/webp", "public, max-age=60")
        head = s3_bucket.head_object(Bucket=BUCKET, Key="d.webp")
        assert head["ContentType"] == "image/webp"
        assert head["CacheControl"] == "public, max-age=60"


class TestClientCache:
    def test_one_client_per_region(self, s3_bucket):
        assert storage._s3("eu-west-1") is storage._s3("eu-west-1")
        assert storage._s3("eu-west-1") is not storage._s3("us-west-2")
