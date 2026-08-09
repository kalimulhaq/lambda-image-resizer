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

        monkeypatch.setattr(storage, "_s3", lambda: SimpleNamespace(head_object=boom))

        with pytest.raises(ClientError):
            storage.derivative_exists(BUCKET, "x.png")
