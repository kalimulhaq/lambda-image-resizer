"""JPEG XL and HEIC come from optional packages. These tests run the library in
a fresh interpreter with a plugin made un-importable, which is the only honest
way to prove the rest keeps working when it is not installed.
"""

import subprocess
import sys

PROBE = """
import lambda_image_resizer.handler
from lambda_image_resizer.params import is_resizable_source, parse_format
print(
    parse_format("jxl"),
    is_resizable_source("a.jxl"),
    is_resizable_source("a.heic"),
    is_resizable_source("a.png"),
)
"""


def probe(*missing: str) -> str:
    blocked = "".join(f"sys.modules[{name!r}] = None\n" for name in missing)
    result = subprocess.run(
        [sys.executable, "-I", "-c", "import sys\n" + blocked + PROBE],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


class TestOptionalCodecs:
    def test_everything_enabled_when_both_plugins_are_installed(self):
        assert probe() == "jxl True True True"

    def test_jxl_is_ignored_without_its_plugin(self):
        assert probe("pillow_jxl") == "None False True True"

    def test_heic_is_ignored_without_its_plugin(self):
        assert probe("pillow_heif") == "jxl True False True"

    def test_core_formats_work_without_either_plugin(self):
        assert probe("pillow_jxl", "pillow_heif") == "None False False True"
