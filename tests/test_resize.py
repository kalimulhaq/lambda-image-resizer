from PIL import Image

from lambda_image_resizer.resize import convert_and_save, fit_inside_no_upscale


def make_image(w: int, h: int, mode: str = "RGB") -> Image.Image:
    return Image.new(mode, (w, h), color=(200, 100, 50) if mode == "RGB" else 128)


class TestFitInsideNoUpscale:
    def test_both_dims_preserves_aspect_ratio_wider_source(self):
        img = make_image(1000, 500)  # 2:1
        out = fit_inside_no_upscale(img, 400, 400)
        assert out.size == (400, 200)  # capped by width, height follows ratio

    def test_both_dims_preserves_aspect_ratio_taller_source(self):
        img = make_image(500, 1000)  # 1:2
        out = fit_inside_no_upscale(img, 400, 400)
        assert out.size == (200, 400)

    def test_width_only_scales_proportionally(self):
        img = make_image(1000, 500)
        out = fit_inside_no_upscale(img, 400, None)
        assert out.size == (400, 200)

    def test_height_only_scales_proportionally(self):
        img = make_image(1000, 500)
        out = fit_inside_no_upscale(img, None, 250)
        assert out.size == (500, 250)

    def test_neither_dim_returns_unchanged(self):
        img = make_image(1000, 500)
        out = fit_inside_no_upscale(img, None, None)
        assert out.size == (1000, 500)
        assert out is img

    def test_never_upscales_both_dims(self):
        img = make_image(200, 100)
        out = fit_inside_no_upscale(img, 2000, 2000)
        assert out.size == (200, 100)  # unchanged, not enlarged

    def test_never_upscales_width_only(self):
        img = make_image(200, 100)
        out = fit_inside_no_upscale(img, 2000, None)
        assert out.size == (200, 100)

    def test_never_crops_result_fits_inside_box(self):
        img = make_image(1000, 300)
        out = fit_inside_no_upscale(img, 400, 400)
        assert out.size[0] <= 400
        assert out.size[1] <= 400

    def test_square_source_and_box(self):
        img = make_image(500, 500)
        out = fit_inside_no_upscale(img, 100, 100)
        assert out.size == (100, 100)


class TestConvertAndSave:
    def test_convert_to_webp(self):
        img = make_image(100, 100)
        data, fmt = convert_and_save(img, "webp", quality=80)
        assert fmt == "webp"
        assert data[:4] == b"RIFF"

    def test_convert_to_jpeg_alias_jpg(self):
        img = make_image(100, 100)
        data, fmt = convert_and_save(img, "jpg", quality=80)
        assert fmt == "jpeg"
        assert data[:2] == b"\xff\xd8"  # JPEG magic bytes

    def test_no_format_keeps_source_format(self):
        img = make_image(100, 100)
        img.format = "PNG"
        data, fmt = convert_and_save(img, None, quality=80)
        assert fmt == "png"
        assert data[:8] == b"\x89PNG\r\n\x1a\n"

    def test_rgba_flattened_for_jpeg(self):
        img = make_image(100, 100, mode="RGBA")
        # should not raise despite JPEG not supporting alpha
        data, fmt = convert_and_save(img, "jpeg", quality=80)
        assert fmt == "jpeg"
        assert len(data) > 0

    def test_quality_applies_to_jpeg_output_size(self):
        img = Image.new("RGB", (300, 300))
        for x in range(300):
            for y in range(300):
                img.putpixel((x, y), ((x * y) % 255, x % 255, y % 255))
        low, _ = convert_and_save(img, "jpeg", quality=10)
        high, _ = convert_and_save(img, "jpeg", quality=95)
        assert len(low) < len(high)
