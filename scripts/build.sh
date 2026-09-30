#!/usr/bin/env bash
# Packages the Lambda deployment zip without Docker.
#
# Pillow ships prebuilt manylinux wheels on PyPI, so pip can fetch the
# correct binary for Lambda's Amazon Linux runtime regardless of the host OS
# running this script.
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON_VERSION="3.13"
BUILD_DIR="package"
ZIP_NAME="function.zip"

rm -rf "$BUILD_DIR" "$ZIP_NAME"
mkdir -p "$BUILD_DIR"

# boto3/botocore are NOT bundled — they're already present in the Lambda
# Python managed runtime, and adding them here would just bloat the zip
# with no benefit.
pip install \
  --platform manylinux2014_x86_64 \
  --target="$BUILD_DIR" \
  --implementation cp \
  --python-version "$PYTHON_VERSION" \
  --only-binary=:all: \
  --upgrade \
  "Pillow>=12.0"

cp -r src/lambda_image_resizer "$BUILD_DIR/"

# Zip via Python's stdlib zipfile rather than shelling out to `zip` — keeps
# this script working on hosts that don't have the zip CLI installed.
python3 - "$BUILD_DIR" "$ZIP_NAME" <<'PYEOF'
import sys
import zipfile
from pathlib import Path

build_dir, zip_name = Path(sys.argv[1]), Path(sys.argv[2])
skip = {".dist-info", "__pycache__"}

with zipfile.ZipFile(zip_name, "w", zipfile.ZIP_DEFLATED) as zf:
    for path in sorted(build_dir.rglob("*")):
        if path.is_dir() or any(part.endswith(tuple(skip)) or part in skip for part in path.parts):
            continue
        zf.write(path, path.relative_to(build_dir))
PYEOF

echo "Built $ZIP_NAME ($(du -h "$ZIP_NAME" | cut -f1))"
