from io import BytesIO

import pytest
from PIL import ExifTags, Image, ImageCms, UnidentifiedImageError

from lambda_image_resizer import resize
from lambda_image_resizer.resize import (
    ImageTooLarge,
    convert_and_save,
    fit_inside_no_upscale,
    load_image,
)


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


def encode(img: Image.Image, fmt: str, **kwargs: object) -> bytes:
    buf = BytesIO()
    img.save(buf, format=fmt, **kwargs)
    return buf.getvalue()


class TestLoadImage:
    def test_returns_source_format(self):
        _, source_format = load_image(encode(make_image(50, 50), "PNG"), None, None)
        assert source_format == "PNG"

    def test_exif_orientation_applied(self):
        # 200x100 stored sideways with orientation 6 (rotate 90 CW) is
        # really a 100x200 portrait photo.
        exif = Image.Exif()
        exif[ExifTags.Base.Orientation] = 6
        data = encode(make_image(200, 100), "JPEG", exif=exif)
        image, _ = load_image(data, None, None)
        assert image.size == (100, 200)

    def test_rotated_jpeg_resizes_to_upright_box(self):
        exif = Image.Exif()
        exif[ExifTags.Base.Orientation] = 6
        data = encode(make_image(2000, 1000), "JPEG", exif=exif)
        image, _ = load_image(data, 100, None)
        assert fit_inside_no_upscale(image, 100, None).size == (100, 200)

    def test_jpeg_draft_decodes_smaller_but_never_below_target(self):
        data = encode(make_image(4000, 2000), "JPEG")
        image, _ = load_image(data, 400, None)
        assert 400 <= image.size[0] < 4000
        assert fit_inside_no_upscale(image, 400, None).size == (400, 200)

    def test_palette_converted_so_resize_is_not_nearest(self):
        data = encode(make_image(64, 64).convert("P"), "PNG")
        image, _ = load_image(data, None, None)
        assert image.mode == "RGB"

    def test_palette_with_transparency_keeps_alpha(self):
        data = encode(make_image(64, 64, mode="RGBA").convert("P"), "GIF", transparency=0)
        image, _ = load_image(data, None, None)
        assert image.mode == "RGBA"

    def test_cmyk_converted_to_rgb_and_profile_dropped(self):
        cmyk = Image.new("CMYK", (32, 32))
        cmyk.info["icc_profile"] = b"fake-cmyk-profile"
        image, _ = load_image(encode(cmyk, "JPEG", icc_profile=b"fake-cmyk-profile"), None, None)
        assert image.mode == "RGB"
        assert "icc_profile" not in image.info

    def test_too_many_pixels_rejected(self, monkeypatch):
        monkeypatch.setattr(resize, "MAX_SOURCE_PIXELS", 100)
        with pytest.raises(ImageTooLarge):
            load_image(encode(make_image(20, 20), "PNG"), None, None)

    def test_disallowed_decoder_rejected(self):
        with pytest.raises(UnidentifiedImageError):
            load_image(encode(make_image(20, 20), "TIFF"), None, None)


class TestConvertAndSaveMetadata:
    def test_icc_profile_preserved(self):
        profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
        img = make_image(32, 32)
        img.info["icc_profile"] = profile
        for fmt in ("jpeg", "webp", "png", "avif"):
            data, _ = convert_and_save(img, fmt, quality=80)
            assert Image.open(BytesIO(data)).info.get("icc_profile") == profile, fmt

    def test_exif_stripped(self):
        exif = Image.Exif()
        exif[ExifTags.Base.Make] = "SecretCam"
        source = Image.open(BytesIO(encode(make_image(32, 32), "JPEG", exif=exif)))
        for fmt in ("jpeg", "webp", "png", "avif"):
            data, _ = convert_and_save(source, fmt, quality=80)
            assert not Image.open(BytesIO(data)).getexif(), fmt

    def test_source_format_argument_wins_over_missing_format(self):
        img = make_image(32, 32)  # .format is None, as after a resize
        _, fmt = convert_and_save(img, None, quality=80, source_format="JPEG")
        assert fmt == "jpeg"

    def test_quality_applies_to_avif(self):
        img = Image.effect_noise((128, 128), 64).convert("RGB")
        low, _ = convert_and_save(img, "avif", quality=10)
        high, _ = convert_and_save(img, "avif", quality=95)
        assert len(low) < len(high)
