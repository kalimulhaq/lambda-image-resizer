import pytest

from lambda_image_resizer.config import ConfigError, OriginConfig


def cf_headers(**kwargs: str) -> dict:
    """Build a CloudFront-shaped customHeaders dict from simple kwargs,
    e.g. cf_headers(x_img_bucket='my-bucket') -> the real nested shape.
    """
    return {key.replace("_", "-"): [{"key": key, "value": value}] for key, value in kwargs.items()}


class TestOriginConfig:
    def test_full_config(self):
        headers = cf_headers(
            **{
                "x-img-bucket": "my-bucket",
                "x-img-resized-prefix": "cache",
                "x-img-quality": "70",
            }
        )
        config = OriginConfig.from_custom_headers(headers)
        assert config.bucket == "my-bucket"
        assert config.resized_prefix == "cache"
        assert config.quality == 70

    def test_missing_bucket_raises(self):
        headers = cf_headers(**{"x-img-resized-prefix": "cache"})
        with pytest.raises(ConfigError):
            OriginConfig.from_custom_headers(headers)

    def test_missing_prefix_defaults_to_resized(self):
        headers = cf_headers(**{"x-img-bucket": "my-bucket"})
        config = OriginConfig.from_custom_headers(headers)
        assert config.resized_prefix == "resized"

    def test_missing_quality_defaults(self):
        headers = cf_headers(**{"x-img-bucket": "my-bucket"})
        config = OriginConfig.from_custom_headers(headers)
        assert config.quality == 82

    def test_invalid_quality_raises(self):
        headers = cf_headers(**{"x-img-bucket": "my-bucket", "x-img-quality": "not-a-number"})
        with pytest.raises(ConfigError):
            OriginConfig.from_custom_headers(headers)

    def test_out_of_range_quality_raises(self):
        headers = cf_headers(**{"x-img-bucket": "my-bucket", "x-img-quality": "150"})
        with pytest.raises(ConfigError):
            OriginConfig.from_custom_headers(headers)

    def test_empty_custom_headers_raises(self):
        with pytest.raises(ConfigError):
            OriginConfig.from_custom_headers({})

    def test_malformed_header_entry_missing_value_key_raises(self):
        # entries[0] present but shaped wrong (no 'value' key) -> KeyError,
        # caught internally and treated as "header not set"
        headers = {"x-img-bucket": [{"key": "X-Img-Bucket"}]}
        with pytest.raises(ConfigError):
            OriginConfig.from_custom_headers(headers)

    def test_malformed_header_entry_not_a_dict_raises(self):
        headers = {"x-img-bucket": ["not-a-dict"]}
        with pytest.raises(ConfigError):
            OriginConfig.from_custom_headers(headers)


class TestOriginConfigLimitsAndHeaders:
    def test_defaults(self):
        config = OriginConfig.from_custom_headers(cf_headers(**{"x-img-bucket": "b"}))
        assert config.max_dimension == 4096
        assert config.allowed_sizes is None
        assert config.cache_control == "public, max-age=31536000, immutable"

    def test_custom_max_dimension(self):
        headers = cf_headers(**{"x-img-bucket": "b", "x-img-max-dimension": "2560"})
        assert OriginConfig.from_custom_headers(headers).max_dimension == 2560

    def test_max_dimension_above_hard_ceiling_raises(self):
        headers = cf_headers(**{"x-img-bucket": "b", "x-img-max-dimension": "100000"})
        with pytest.raises(ConfigError):
            OriginConfig.from_custom_headers(headers)

    def test_allowed_sizes_parsed_sorted_and_deduplicated(self):
        headers = cf_headers(**{"x-img-bucket": "b", "x-img-allowed-sizes": "1280, 320,640,320"})
        assert OriginConfig.from_custom_headers(headers).allowed_sizes == (320, 640, 1280)

    def test_allowed_sizes_above_max_raises(self):
        headers = cf_headers(
            **{"x-img-bucket": "b", "x-img-max-dimension": "1000", "x-img-allowed-sizes": "2000"}
        )
        with pytest.raises(ConfigError):
            OriginConfig.from_custom_headers(headers)

    def test_allowed_sizes_garbage_raises(self):
        headers = cf_headers(**{"x-img-bucket": "b", "x-img-allowed-sizes": "small,large"})
        with pytest.raises(ConfigError):
            OriginConfig.from_custom_headers(headers)

    def test_custom_cache_control(self):
        headers = cf_headers(**{"x-img-bucket": "b", "x-img-cache-control": "public, max-age=60"})
        assert OriginConfig.from_custom_headers(headers).cache_control == "public, max-age=60"

    def test_empty_prefix_raises(self):
        headers = cf_headers(**{"x-img-bucket": "b", "x-img-resized-prefix": "/"})
        with pytest.raises(ConfigError):
            OriginConfig.from_custom_headers(headers)
