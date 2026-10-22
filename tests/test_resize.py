from io import BytesIO

import pytest
from PIL import ExifTags, Image, ImageChops, ImageCms, UnidentifiedImageError

from lambda_image_resizer import resize
from lambda_image_resizer.resize import (
    ImageTooLarge,
    convert_and_save,
    fill_box,
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


class TestFillBox:
    def test_wider_source_gets_exact_size(self):
        assert fill_box(make_image(1000, 500), 520, 400).size == (520, 400)

    def test_taller_source_gets_exact_size(self):
        assert fill_box(make_image(500, 1000), 520, 400).size == (520, 400)

    def test_smaller_source_is_enlarged_to_the_exact_size(self):
        # crop=true promises exact dimensions, so it may enlarge (unlike fit).
        assert fill_box(make_image(200, 100), 520, 400).size == (520, 400)

    def test_wide_source_is_cropped_from_the_centre_not_squashed(self):
        wide = Image.new("RGB", (1000, 500), "white")
        wide.paste((0, 0, 0), (400, 0, 600, 500))
        out = fill_box(wide, 500, 500)
        # The 500px window is x=250..750, so the band lands on x=150..350.
        # Squashing the whole width would put it on x=200..300 instead.
        assert out.getpixel((160, 250)) == (0, 0, 0)
        assert out.getpixel((340, 250)) == (0, 0, 0)
        assert out.getpixel((140, 250)) == (255, 255, 255)
        assert out.getpixel((360, 250)) == (255, 255, 255)

    def test_tall_source_is_cropped_from_the_centre_not_squashed(self):
        tall = Image.new("RGB", (500, 1000), "white")
        tall.paste((0, 0, 0), (0, 400, 500, 600))
        out = fill_box(tall, 500, 500)
        assert out.getpixel((250, 160)) == (0, 0, 0)
        assert out.getpixel((250, 340)) == (0, 0, 0)
        assert out.getpixel((250, 140)) == (255, 255, 255)
        assert out.getpixel((250, 360)) == (255, 255, 255)

    def test_float_rounding_never_pushes_the_window_outside_the_source(self):
        # The source window is computed in floats and Pillow rejects any box
        # outside the image, even by 1e-15. These sizes each overshoot by that
        # much on one edge (found by sweeping random sizes).
        for source, box in [
            ((29, 35), (31, 36)),
            ((41, 14), (53, 61)),
            ((33, 13), (49, 60)),
            ((7, 31), (41, 18)),
        ]:
            assert fill_box(make_image(*source), *box).size == box, (source, box)

    def test_centre_crop_holds_when_scaling_down(self):
        wide = Image.new("RGB", (2000, 1000), "white")
        wide.paste((0, 0, 0), (900, 0, 1100, 1000))
        out = fill_box(wide, 500, 500)
        # Cover scale 0.5 -> a 1000px window at x=500..1500 -> band at 200..300.
        assert out.getpixel((250, 250)) == (0, 0, 0)
        assert out.getpixel((150, 250)) == (255, 255, 255)
        assert out.getpixel((350, 250)) == (255, 255, 255)


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

    def test_browser_unsupported_sources_default_to_jpeg(self):
        for source_format in ("HEIF", "TIFF"):
            data, fmt = convert_and_save(make_image(32, 32), None, 80, source_format=source_format)
            assert fmt == "jpeg", source_format
            assert data[:2] == b"\xff\xd8", source_format

    def test_requested_format_wins_over_the_jpeg_default(self):
        _, fmt = convert_and_save(make_image(32, 32), "webp", 80, source_format="HEIF")
        assert fmt == "webp"

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

    def test_jpeg_draft_for_crop_keeps_enough_pixels_to_cover_the_box(self):
        data = encode(make_image(4000, 2000), "JPEG")
        image, _ = load_image(data, 400, 400, crop=True)
        # Covering 400x400 needs at least 800x400; a fit-sized draft (400x200)
        # would decode too small and the crop would be upscaled from it.
        assert image.size[0] >= 800
        assert image.size[1] >= 400
        assert image.size[0] < 4000  # still decoded at reduced scale

    def test_rotated_jpeg_with_crop_fills_the_upright_box(self):
        exif = Image.Exif()
        exif[ExifTags.Base.Orientation] = 6
        data = encode(make_image(2000, 1000), "JPEG", exif=exif)
        image, _ = load_image(data, 100, 100, crop=True)
        assert image.size[1] > image.size[0]  # upright portrait
        assert fill_box(image, 100, 100).size == (100, 100)

    def test_avif_source_is_decodable(self):
        image, source_format = load_image(encode(make_image(40, 20), "AVIF"), None, None)
        assert source_format == "AVIF"
        assert image.size == (40, 20)

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
            load_image(encode(make_image(20, 20), "PPM"), None, None)

    def test_tiff_source_is_decodable(self):
        image, source_format = load_image(encode(make_image(40, 20), "TIFF"), None, None)
        assert source_format == "TIFF"
        assert image.size == (40, 20)

    def test_sixteen_bit_greyscale_is_scaled_not_clipped_to_white(self):
        # Mid-grey 32768/65535. Plain convert() clamps every 16-bit value
        # above 255 to white.
        for fmt in ("TIFF", "PNG"):
            image, _ = load_image(encode(Image.new("I;16", (8, 8), 32768), fmt), None, None)
            assert abs(image.convert("L").getpixel((0, 0)) - 128) <= 1, fmt

    def test_heic_source_is_decodable_and_rotated_once(self):
        # 200x100 pixels tagged orientation 6 is a 100x200 portrait. The HEIC
        # decoder rotates it itself and resets the tag, so we must not rotate
        # a second time.
        exif = Image.Exif()
        exif[ExifTags.Base.Orientation] = 6
        data = encode(make_image(200, 100), "HEIF", exif=exif.tobytes())
        image, source_format = load_image(data, None, None)
        assert source_format == "HEIF"
        assert image.size == (100, 200)


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
        for fmt in ("jpeg", "webp", "png", "avif", "jxl"):
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


class TestJxlOutput:
    def test_round_trips_through_the_jxl_decoder(self):
        data, fmt = convert_and_save(make_image(100, 50), "jxl", quality=80)
        assert fmt == "jxl"
        image, source_format = load_image(data, None, None)
        assert source_format == "JXL"
        assert image.size == (100, 50)

    def test_alpha_is_kept(self):
        rgba = Image.new("RGBA", (32, 32), (200, 100, 50, 77))
        data, _ = convert_and_save(rgba, "jxl", quality=90)
        image, _ = load_image(data, None, None)
        assert image.mode == "RGBA"
        assert abs(image.getpixel((0, 0))[3] - 77) <= 2

    def test_quality_applies(self):
        img = Image.effect_noise((128, 128), 64).convert("RGB")
        low, _ = convert_and_save(img, "jxl", quality=10)
        high, _ = convert_and_save(img, "jxl", quality=95)
        assert len(low) < len(high)

    def test_quality_100_is_lossless(self):
        # The plugin raises on quality=100 unless lossless is requested, and
        # X-Img-Quality allows 100.
        img = Image.effect_noise((32, 32), 64).convert("RGB")
        data, _ = convert_and_save(img, "jxl", quality=100)
        decoded, _ = load_image(data, None, None)
        assert ImageChops.difference(decoded, img).getbbox() is None

    def test_file_backed_jpeg_is_encoded_from_its_pixels_not_its_file(self, tmp_path):
        # The JXL plugin re-encodes the file on disk (ignoring any resize) when
        # handed a JPEG image that still has a filename. draft() shrinks the
        # pixels in place without clearing either.
        path = tmp_path / "photo.jpg"
        make_image(400, 200).save(path, format="JPEG")
        image = Image.open(path)
        image.draft("RGB", (100, 50))
        image.load()
        assert image.size == (100, 50)
        data, _ = convert_and_save(image, "jxl", quality=80)
        assert load_image(data, None, None)[0].size == (100, 50)
