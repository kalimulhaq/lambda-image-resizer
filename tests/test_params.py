from lambda_image_resizer.params import (
    is_resizable_source,
    parse_dimension,
    parse_format,
    source_extension,
)


class TestParseDimension:
    def test_valid_value(self):
        assert parse_dimension("500") == 500

    def test_none_is_none(self):
        assert parse_dimension(None) is None

    def test_non_numeric_is_none(self):
        assert parse_dimension("abc") is None
        assert parse_dimension("50.5") is None
        assert parse_dimension("") is None

    def test_negative_is_none(self):
        # isdigit() already rejects a leading '-', covered here for clarity
        assert parse_dimension("-50") is None

    def test_zero_is_none(self):
        assert parse_dimension("0") is None

    def test_clamped_to_max(self):
        assert parse_dimension("999999") == 2400

    def test_clamped_to_min(self):
        assert parse_dimension("1") == 16

    def test_within_bounds_unchanged(self):
        assert parse_dimension("1200") == 1200


class TestParseFormat:
    def test_valid_formats(self):
        for fmt in ("webp", "avif", "jpeg", "jpg", "png"):
            assert parse_format(fmt) == fmt

    def test_case_insensitive(self):
        assert parse_format("WEBP") == "webp"

    def test_none_is_none(self):
        assert parse_format(None) is None

    def test_unsupported_format_is_none(self):
        assert parse_format("bmp") is None
        assert parse_format("svg") is None
        assert parse_format("exe") is None

    def test_empty_string_is_none(self):
        assert parse_format("") is None


class TestSourceExtension:
    def test_simple(self):
        assert source_extension("uploads/products/pro-01.png") == "png"

    def test_uppercase(self):
        assert source_extension("uploads/products/PRO-01.JPG") == "jpg"

    def test_no_extension(self):
        assert source_extension("uploads/products/no-extension") == ""

    def test_dot_in_directory_name_not_mistaken_for_extension(self):
        assert source_extension("uploads/v1.2/pro-01.png") == "png"

    def test_dot_only_in_directory_no_file_extension(self):
        assert source_extension("uploads/v1.2/no-extension") == ""


class TestIsResizableSource:
    def test_allowed_extensions(self):
        for ext in ("jpg", "jpeg", "png", "gif", "webp", "bmp"):
            assert is_resizable_source(f"uploads/x.{ext}") is True

    def test_svg_is_excluded(self):
        assert is_resizable_source("uploads/logo.svg") is False

    def test_non_image_excluded(self):
        assert is_resizable_source("documents/report.pdf") is False

    def test_no_extension_excluded(self):
        assert is_resizable_source("uploads/no-extension") is False

    def test_uppercase_extension_allowed(self):
        assert is_resizable_source("uploads/PHOTO.PNG") is True
