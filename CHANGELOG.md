# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

### Added
- `crop=true`: with both dimensions (`w` and `h`, or `d=WxH`) the image is scaled to cover the box and cropped from the centre to exactly that size. It enlarges sources smaller than the box. Crops get their own derivative key (`w520h400c`), so existing derivatives are unaffected.
- JPEG XL (`f=jxl` output and `.jxl` sources) and HEIC/HEIF sources (iPhone photos), as **optional** codecs. They come from `pillow-jxl-plugin` and `pillow-heif`, which are GPL-licensed, so they are only in the new `function-full.zip` (or `pip install ".[jxl,heic]"`). Without them `f=jxl` is ignored and those files are passed through. `X-Img-Quality` applies to JPEG XL, and `100` means lossless.
- TIFF (`.tif`, `.tiff`), AVIF and `.jfif` files are now accepted as sources (AVIF was previously output-only). Sources browsers can't display (HEIC, TIFF) are converted to JPEG when no `f=` is given.
- Releases publish `function-full.zip` (and its `.sha256`) next to `function.zip`. `scripts/build.sh --full` builds it, and `scripts/deploy.sh` takes a `ZIP_FILE` override.
- Both zips now carry the licence texts of the packages bundled in them, under `THIRD_PARTY_LICENSES/`.
- README documentation for the `d=` parameter, for using the function with a CloudFront origin group, and a Licensing section.

### Changed
- `d=WxH` is now a documented, permanent parameter and is **width-only**: `d=500x333` scales to 500px wide and the height follows, instead of fitting inside the 500×333 box as in 0.2.0. `d=x250` still scales by height, and explicit `w`/`h` still win over `d`. `d=500x333` now shares the `w500` derivative with `?w=500`; derivatives written by 0.2.0 under `w500h333` for `d=` requests are no longer used.
- `crop=true` skips `X-Img-Allowed-Sizes` snapping, since snapping each side would change the box's shape. Crop sizes are still clamped to `X-Img-Max-Dimension`.
- `infra/cache-policy.example.json` now forwards `d` and `crop` as well as `w`, `h` and `f`.
- Pillow is capped below 13 (the major version the tests run on), and `scripts/build.sh` now fetches `manylinux_2_28` wheels, so the zip moves from Pillow 12.2.0 to 12.3.0.

### Fixed
- 16-bit greyscale PNG and TIFF images no longer turn pure white; they are scaled down to 8 bits.

### Security
- The AVIF and TIFF decoders now also see untrusted input, in addition to JPEG, PNG, GIF, WebP and BMP (and JPEG XL and HEIF in the full build). The 25 MB and 50 megapixel limits still apply before decoding.
- JPEG XL output never carries over EXIF metadata (the plugin would otherwise copy it from the source), and is always encoded from the resized pixels rather than from the original file.

### Upgrading
- **Your cache policy must forward the `d` and `crop` query strings** (see `infra/cache-policy.example.json`). Without them, requests that differ only in `d` or `crop` share one cache entry and can be served the wrong variant.
- Callers that relied on 0.2.0's box-fitting `d=WxH` should switch to `w=` and `h=`.
- To use JPEG XL or HEIC, deploy `function-full.zip` and read the Licensing section of the README first. JPEG XL output does not carry an embedded colour profile over from the source; it is written as sRGB.

## [0.2.0] - 2026-09-30

### Added
- `Cache-Control` on every derivative (default `public, max-age=31536000, immutable`, configurable via `X-Img-Cache-Control`).
- `X-Img-Max-Dimension` origin header (default raised from 2400 to 4096, hard ceiling 8192).
- `X-Img-Allowed-Sizes` origin header: snaps requested sizes to a fixed list to cap how many derivatives can exist.
- `infra/response-headers-policy.example.json`: security headers, fallback `Cache-Control`, and removal of `Server`/`x-amz-*` headers.
- `MEMORY_SIZE` / `TIMEOUT` overrides in `scripts/deploy.sh`.
- Releases now ship a `function.zip.sha256` checksum, use this CHANGELOG's section as their notes, and fail if the tag doesn't match the package version. The README explains how to download, verify and deploy a release without cloning or building.

### Changed
- Large JPEGs are decoded at reduced scale (libjpeg draft mode), and resizing uses a fast integer pre-reduction — much faster on big photos.
- S3 clients are created per bucket region (from the CloudFront event), with short timeouts and bounded retries.
- JPEGs are saved progressive + optimized; WebP uses a better compression method; AVIF now honours `X-Img-Quality`.
- The query string is dropped from requests rewritten to a derivative.
- Default memory raised from 512MB to 1024MB.
- The example S3 policy only allows writes under `resized/*`; the example cache policy no longer splits images by `Accept-Encoding`.
- Minimum Pillow version raised to 12.0.

### Fixed
- Keys with spaces or non-ASCII characters (percent-encoded in the URI) are now found in S3.
- Photos are rotated according to their EXIF orientation.
- Palette PNGs/GIFs are resized with LANCZOS instead of nearest-neighbour.
- CMYK and 16-bit sources no longer fail to convert.
- Embedded ICC colour profiles are preserved.

### Security
- Only the JPEG, PNG, GIF, WebP and BMP decoders are ever used on untrusted input.
- Originals over 25 MB or 50 megapixels are served as-is instead of being decoded.
- Derivatives are never used as sources (no derivative-of-derivative chains).
- EXIF metadata (including GPS) is stripped from derivatives.

### Upgrading
- Deploy the new `function.zip`, publish a version, and point your CloudFront association at it. No configuration changes are required.
- Optional: apply the tighter `infra/s3-policy.example.json`, turn off the `Accept-Encoding` settings in your cache policy, and attach `infra/response-headers-policy.example.json`.
- Derivatives created before this release have no `Cache-Control` and use the old encoder settings. To regenerate them, delete the `resized/` prefix and invalidate `/*`.

### Other
- The README was reorganised and a CONTRIBUTING guide added. There's also a pull request template, and local Claude Code files are now ignored.

## [0.1.0] - Not released

### Added
- Initial release: Lambda@Edge `origin-request` image resizer/format-converter backed by Pillow.
- `?w=&h=&f=` query interface — fit-inside resize (never crop, never distort, never upscale), with independent width/height and an output format allow-list.
- Config passed via CloudFront origin custom headers (`X-Img-Bucket`, `X-Img-Resized-Prefix`, `X-Img-Quality`) — no code changes needed to reuse across projects.
- Derivative persistence to S3, keyed deterministically, so a resized/converted variant is computed at most once.
- Every validation failure or unexpected error falls back to serving the original file — never a generated error response.
- Full pytest suite (pure-function unit tests + `moto`-backed integration tests), `ruff` + `mypy` clean, GitHub Actions CI and release workflows.
