"""Resize and format-conversion logic, built on Pillow.

The default resize is deliberately narrow: fit the image inside the
requested box, preserving aspect ratio, never cropping, never distorting,
and never upscaling past the source resolution. The one opt-in exception is
crop=true (fill_box), which returns exactly the requested size.
"""

from __future__ import annotations

from io import BytesIO

from PIL import ExifTags, Image, ImageOps

from .codecs import HAS_HEIF, HAS_JXL

# Only these decoders ever see untrusted bytes — Pillow would otherwise try
# every plugin it has, based on the file's content rather than its extension.
_ALLOWED_DECODERS = (
    ("JPEG", "PNG", "GIF", "WEBP", "AVIF", "TIFF", "BMP")
    + (("JXL",) if HAS_JXL else ())
    + (("HEIF",) if HAS_HEIF else ())
)

# Source formats browsers can't display. With no output format requested they
# are converted to JPEG instead of being re-saved in their own format.
_BROWSER_UNSUPPORTED_SOURCES = frozenset({"HEIF", "TIFF"})

# Reject sources above this pixel count before decoding them (a 50MP RGBA
# image is ~200MB decoded). Pillow's own guard only warns until 2x its
# default of ~89MP.
MAX_SOURCE_PIXELS = 50_000_000

# Formats whose Pillow plugin accepts a `quality` kwarg.
_QUALITY_AWARE_FORMATS = frozenset({"jpeg", "webp", "avif", "jxl"})

# Formats without alpha-channel support — an RGBA/P-mode source must be
# flattened onto an opaque background before saving as one of these.
_NO_ALPHA_FORMATS = frozenset({"jpeg"})

# Formats that can embed an ICC colour profile.
_ICC_AWARE_FORMATS = frozenset({"jpeg", "webp", "avif", "png"})

# EXIF orientations that swap width and height (90/270 degree rotations).
_TRANSPOSING_ORIENTATIONS = frozenset({5, 6, 7, 8})

# Modes that resize and save cleanly without conversion.
_NATIVE_MODES = frozenset({"RGB", "RGBA", "L", "LA"})


class ImageTooLarge(Exception):
    """Raised when a source image exceeds MAX_SOURCE_PIXELS."""


def fit_size(size: tuple[int, int], target_w: int | None, target_h: int | None) -> tuple[int, int]:
    """Return the size `size` becomes when fitted inside (target_w, target_h),
    preserving aspect ratio and never enlarging. Either target may be None.
    """
    orig_w, orig_h = size

    if target_w is None and target_h is None:
        return size

    if target_w is None:
        assert target_h is not None
        scale = min(target_h / orig_h, 1.0)
    elif target_h is None:
        scale = min(target_w / orig_w, 1.0)
    else:
        scale = min(target_w / orig_w, target_h / orig_h, 1.0)

    return (max(1, round(orig_w * scale)), max(1, round(orig_h * scale)))


def cover_size(size: tuple[int, int], target_w: int, target_h: int) -> tuple[int, int]:
    """Return the size `size` becomes when scaled, up or down, to just cover
    (target_w, target_h) while preserving aspect ratio.
    """
    orig_w, orig_h = size
    scale = max(target_w / orig_w, target_h / orig_h)
    return (max(1, round(orig_w * scale)), max(1, round(orig_h * scale)))


def fill_box(image: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Return `image` scaled to cover (target_w, target_h) and cropped from
    the centre to exactly that size, preserving aspect ratio.

    Unlike fit_inside_no_upscale this enlarges small sources: a caller asks
    for crop=true when it needs the exact dimensions.
    """
    orig_w, orig_h = image.size
    scale = max(target_w / orig_w, target_h / orig_h)
    window_w, window_h = target_w / scale, target_h / scale
    # Pillow rejects a box outside the image by even 1e-15, which float
    # rounding can produce, hence the clamps.
    left = max(0.0, (orig_w - window_w) / 2)
    top = max(0.0, (orig_h - window_h) / 2)
    # One resample straight from the centred source window to the target size.
    box = (left, top, min(float(orig_w), left + window_w), min(float(orig_h), top + window_h))
    return image.resize((target_w, target_h), Image.Resampling.LANCZOS, box=box, reducing_gap=3.0)


def fit_inside_no_upscale(
    image: Image.Image, target_w: int | None, target_h: int | None
) -> Image.Image:
    """Return `image` scaled to fit inside (target_w, target_h), preserving
    aspect ratio, never cropping, and never enlarging past the source size.

    Either target may be None (scale proportionally to the other), or both
    may be None (no-op, image returned unchanged).
    """
    new_size = fit_size(image.size, target_w, target_h)
    if new_size == image.size:
        return image
    # reducing_gap does a cheap integer-factor reduce first, then LANCZOS for
    # the remainder — much faster on large downscales, visually identical.
    return image.resize(new_size, Image.Resampling.LANCZOS, reducing_gap=3.0)


def _draft_size(
    size: tuple[int, int], target_w: int | None, target_h: int | None, crop: bool
) -> tuple[int, int]:
    """The smallest size a draft decode may leave: the fitted size, or the
    covering size when the result will be cropped to fill the box.
    """
    if crop and target_w is not None and target_h is not None:
        return cover_size(size, target_w, target_h)
    return fit_size(size, target_w, target_h)


def load_image(
    data: bytes, target_w: int | None, target_h: int | None, crop: bool = False
) -> tuple[Image.Image, str | None]:
    """Decode untrusted `data` into an upright image ready for resizing.

    `crop` says the result will be cropped to fill the box rather than fitted
    inside it. Returns (image, source_format). Raises ImageTooLarge, or
    Pillow's UnidentifiedImageError for anything that isn't an allowed format.
    """
    image: Image.Image = Image.open(BytesIO(data), formats=_ALLOWED_DECODERS)
    source_format = image.format

    width, height = image.size
    if width * height > MAX_SOURCE_PIXELS:
        raise ImageTooLarge(f"{width}x{height} exceeds {MAX_SOURCE_PIXELS} pixels")

    orientation = image.getexif().get(ExifTags.Base.Orientation, 1)

    if source_format == "JPEG" and (target_w is not None or target_h is not None):
        # Let libjpeg decode at 1/2, 1/4 or 1/8 scale when that still leaves
        # at least the target size — far less work than a full decode. The
        # target is in upright space, so swap it for rotated sources.
        if orientation in _TRANSPOSING_ORIENTATIONS:
            raw_box = _draft_size((height, width), target_w, target_h, crop)[::-1]
        else:
            raw_box = _draft_size((width, height), target_w, target_h, crop)
        image.draft(image.mode, (raw_box[0], raw_box[1]))

    if orientation != 1:
        # Rotate phone photos upright; the orientation tag is dropped on save.
        image = ImageOps.exif_transpose(image)
    else:
        image.load()

    return _normalize_mode(image), source_format


def _normalize_mode(image: Image.Image) -> Image.Image:
    """Convert palette/CMYK/16-bit/etc. sources to RGB(A)/L(A).

    Palette images in particular must be converted before resizing: Pillow
    silently downgrades any resample filter to NEAREST for mode 'P'.
    """
    if image.mode in _NATIVE_MODES:
        return image
    if image.mode.startswith("I;16"):
        # convert() clamps 16-bit greyscale values above 255 to white, so
        # scale down to 8 bits first.
        return image.point(lambda value: value / 256).convert("L")
    if image.mode == "CMYK":
        # The embedded profile describes CMYK, not the RGB we're producing.
        converted = image.convert("RGB")
        converted.info.pop("icc_profile", None)
        return converted
    return image.convert("RGBA" if image.has_transparency_data else "RGB")


def _pillow_format_name(fmt: str) -> str:
    return "JPEG" if fmt == "jpg" else fmt.upper()


def convert_and_save(
    image: Image.Image,
    fmt: str | None,
    quality: int,
    source_format: str | None = None,
) -> tuple[bytes, str]:
    """Save `image` to bytes in `fmt` (or the source format if fmt is None),
    returning (bytes, format_used_lowercase).

    `source_format` defaults to `image.format`; pass it explicitly when the
    image has been through operations that drop `.format`.
    """
    pillow_format = _pillow_format_name(fmt) if fmt else (source_format or image.format or "PNG")
    if not fmt and pillow_format in _BROWSER_UNSUPPORTED_SOURCES:
        pillow_format = "JPEG"
    normalized_fmt = pillow_format.lower()
    normalized_fmt = "jpeg" if normalized_fmt == "jpg" else normalized_fmt

    icc_profile = image.info.get("icc_profile")

    if normalized_fmt in _NO_ALPHA_FORMATS and image.mode in ("RGBA", "LA", "P"):
        background = Image.new("RGB", image.size, (255, 255, 255))
        rgba = image.convert("RGBA")
        background.paste(rgba, mask=rgba.split()[-1])
        image = background

    # EXIF (camera, GPS location, ...) is never carried over to derivatives.
    save_kwargs: dict[str, object] = {}
    if normalized_fmt in _QUALITY_AWARE_FORMATS:
        save_kwargs["quality"] = quality
    if normalized_fmt in _ICC_AWARE_FORMATS and icc_profile:
        save_kwargs["icc_profile"] = icc_profile
    if normalized_fmt == "jpeg":
        save_kwargs.update(optimize=True, progressive=True)
    elif normalized_fmt == "webp":
        save_kwargs["method"] = 5
    elif normalized_fmt == "jxl":
        # The JXL plugin copies EXIF from the image unless told otherwise, can't
        # encode quality 100 unless it is lossless, and re-encodes the file on
        # disk instead of the pixels for a file-backed JPEG.
        save_kwargs.update(exif=b"", lossless=quality >= 100, lossless_jpeg=False)

    buffer = BytesIO()
    image.save(buffer, format=pillow_format, **save_kwargs)
    return buffer.getvalue(), normalized_fmt
