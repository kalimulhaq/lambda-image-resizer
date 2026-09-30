from lambda_image_resizer.keys import derivative_key, is_derivative_key


class TestDerivativeKey:
    def test_both_dimensions(self):
        key = derivative_key("uploads/products/pro-01.png", "resized", 500, 333, "webp")
        assert key == "resized/w500h333/webp/uploads/products/pro-01.png"

    def test_width_only(self):
        key = derivative_key("uploads/products/pro-01.png", "resized", 500, None, "webp")
        assert key == "resized/w500/webp/uploads/products/pro-01.png"

    def test_height_only(self):
        key = derivative_key("uploads/products/pro-01.png", "resized", None, 333, "webp")
        assert key == "resized/h333/webp/uploads/products/pro-01.png"

    def test_no_dimensions_format_only(self):
        key = derivative_key("uploads/products/pro-01.png", "resized", None, None, "webp")
        assert key == "resized/orig/webp/uploads/products/pro-01.png"

    def test_no_format_dimensions_only(self):
        key = derivative_key("uploads/products/pro-01.png", "resized", 500, 333, None)
        assert key == "resized/w500h333/orig/uploads/products/pro-01.png"

    def test_leading_slash_on_original_key_stripped(self):
        key = derivative_key("/uploads/products/pro-01.png", "resized", 500, None, "webp")
        assert key == "resized/w500/webp/uploads/products/pro-01.png"

    def test_prefix_slashes_normalized(self):
        key = derivative_key("uploads/x.png", "/resized/", 500, None, "webp")
        assert key == "resized/w500/webp/uploads/x.png"

    def test_never_collides_across_combinations(self):
        combos = [
            (500, 333, "webp"),
            (500, None, "webp"),
            (None, 333, "webp"),
            (None, None, "webp"),
            (500, 333, None),
            (500, 333, "png"),
        ]
        keys = {derivative_key("uploads/x.png", "resized", w, h, f) for (w, h, f) in combos}
        assert len(keys) == len(combos)


class TestIsDerivativeKey:
    def test_under_prefix(self):
        assert is_derivative_key("resized/w500/webp/uploads/x.png", "resized") is True

    def test_not_under_prefix(self):
        assert is_derivative_key("uploads/x.png", "resized") is False

    def test_prefix_must_be_a_whole_path_segment(self):
        assert is_derivative_key("resized-photos/x.png", "resized") is False

    def test_prefix_slashes_normalized(self):
        assert is_derivative_key("/cache/w1/orig/x.png", "/cache/") is True
