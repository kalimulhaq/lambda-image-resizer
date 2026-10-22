"""Optional image codecs.

JPEG XL and HEIC are handled by separate packages that are not hard
dependencies, because their licences are stricter than this project's:
pillow-jxl-plugin is GPL-3.0-or-later, and pillow-heif's binary wheels bundle
GPL and LGPL codecs (including the x265 HEVC encoder). Each one is registered
with Pillow only if it is importable; the HAS_* flags tell the rest of the code
which formats are available, and everything else keeps working without them.
"""

from __future__ import annotations

try:
    import pillow_jxl  # noqa: F401 - registers the JPEG XL format with Pillow

    HAS_JXL = True
except ImportError:
    HAS_JXL = False

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
    HAS_HEIF = True
except ImportError:
    HAS_HEIF = False
