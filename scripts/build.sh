#!/usr/bin/env bash
# Packages the Lambda deployment zip without Docker.
#
# Pillow ships prebuilt manylinux wheels on PyPI, so pip can fetch the
# correct binary for Lambda's Amazon Linux runtime regardless of the host OS
# running this script.
#
# Usage:
#   ./scripts/build.sh          -> function.zip       Pillow only (permissive licences)
#   ./scripts/build.sh --full   -> function-full.zip  adds JPEG XL and HEIC support
#
# The full build bundles pillow-jxl-plugin (GPL-3.0-or-later) and pillow-heif's
# binary wheels (GPLv2/LGPLv3 codecs, including x265). See "Licensing" in the
# README before distributing it.
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON_VERSION="3.13"
BUILD_DIR="package"
ZIP_NAME="function.zip"
# Pillow is capped at the major version the tests run against.
PACKAGES=("Pillow>=12.0,<13")
# manylinux_2_28 wheels (the newest Pillow, and the only pillow-heif ones) run on
# Lambda's Amazon Linux 2023 runtime; manylinux2014 is the fallback for packages
# that only ship the older tag.
PLATFORMS=(--platform manylinux_2_28_x86_64 --platform manylinux2014_x86_64)

case "${1:-}" in
  "") ;;
  --full)
    ZIP_NAME="function-full.zip"
    PACKAGES+=("pillow-jxl-plugin>=1.3" "pillow-heif>=1.0")
    ;;
  *)
    echo "Usage: $0 [--full]" >&2
    exit 1
    ;;
esac

rm -rf "$BUILD_DIR" "$ZIP_NAME"
mkdir -p "$BUILD_DIR"

# boto3/botocore are NOT bundled — they're already present in the Lambda
# Python managed runtime, and adding them here would just bloat the zip
# with no benefit.
pip install \
  "${PLATFORMS[@]}" \
  --target="$BUILD_DIR" \
  --implementation cp \
  --python-version "$PYTHON_VERSION" \
  --only-binary=:all: \
  --upgrade \
  "${PACKAGES[@]}"

cp -r src/lambda_image_resizer "$BUILD_DIR/"

# Zip via Python's stdlib zipfile rather than shelling out to `zip` — keeps
# this script working on hosts that don't have the zip CLI installed.
#
# The *.dist-info directories are left out, except for their licence files:
# those are kept under THIRD_PARTY_LICENSES/<package>/ because the bundled
# packages' licences require their notices to travel with the binaries.
python3 - "$BUILD_DIR" "$ZIP_NAME" <<'PYEOF'
import sys
import zipfile
from pathlib import Path

build_dir, zip_name = Path(sys.argv[1]), Path(sys.argv[2])
LICENSE_PREFIXES = ("license", "licence", "copying", "notice")

with zipfile.ZipFile(zip_name, "w", zipfile.ZIP_DEFLATED) as zf:
    for path in sorted(build_dir.rglob("*")):
        if path.is_dir() or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(build_dir)
        dist_info = next((part for part in relative.parts if part.endswith(".dist-info")), None)
        if dist_info is None:
            zf.write(path, relative)
        elif path.name.lower().startswith(LICENSE_PREFIXES):
            package = dist_info.removesuffix(".dist-info")
            zf.write(path, Path("THIRD_PARTY_LICENSES") / package / path.name)
PYEOF

echo "Built $ZIP_NAME ($(du -h "$ZIP_NAME" | cut -f1))"
