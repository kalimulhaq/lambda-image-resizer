"""Resize and format-conversion logic, built on Pillow.

The resize behavior is deliberately narrow: fit the image inside the
requested box, preserving aspect ratio, never cropping, never distorting,
and never upscaling past the source resolution.
"""

from __future__ import annotations

from io import BytesIO

from PIL import Image

# Formats whose Pillow plugin accepts a `quality` kwarg.
_QUALITY_AWARE_FORMATS = frozenset({"jpeg", "webp"})

# Formats without alpha-channel support — an RGBA/P-mode source must be
# flattened onto an opaque background before saving as one of these.
_NO_ALPHA_FORMATS = frozenset({"jpeg"})


def fit_inside_no_upscale(
    image: Image.Image, target_w: int | None, target_h: int | None
) -> Image.Image:
    """Return `image` scaled to fit inside (target_w, target_h), preserving
    aspect ratio, never cropping, and never enlarging past the source size.

    Either target may be None (scale proportionally to the other), or both
    may be None (no-op, image returned unchanged).
    """
    orig_w, orig_h = image.size

    if target_w is None and target_h is None:
        return image

    if target_w is None:
        assert target_h is not None
        scale = min(target_h / orig_h, 1.0)
    elif target_h is None:
        scale = min(target_w / orig_w, 1.0)
    else:
        scale = min(target_w / orig_w, target_h / orig_h, 1.0)

    new_size = (max(1, round(orig_w * scale)), max(1, round(orig_h * scale)))
    if new_size == (orig_w, orig_h):
        return image
    return image.resize(new_size, Image.Resampling.LANCZOS)


def _pillow_format_name(fmt: str) -> str:
    return "JPEG" if fmt == "jpg" else fmt.upper()


def convert_and_save(image: Image.Image, fmt: str | None, quality: int) -> tuple[bytes, str]:
    """Save `image` to bytes in `fmt` (or the image's own format if fmt is
    None), returning (bytes, format_used_lowercase).
    """
    pillow_format = _pillow_format_name(fmt) if fmt else (image.format or "PNG")
    normalized_fmt = pillow_format.lower()
    normalized_fmt = "jpeg" if normalized_fmt == "jpg" else normalized_fmt

    if normalized_fmt in _NO_ALPHA_FORMATS and image.mode in ("RGBA", "LA", "P"):
        background = Image.new("RGB", image.size, (255, 255, 255))
        rgba = image.convert("RGBA")
        background.paste(rgba, mask=rgba.split()[-1])
        image = background

    save_kwargs: dict[str, object] = {}
    if normalized_fmt in _QUALITY_AWARE_FORMATS:
        save_kwargs["quality"] = quality

    buffer = BytesIO()
    image.save(buffer, format=pillow_format, **save_kwargs)
    return buffer.getvalue(), normalized_fmt
