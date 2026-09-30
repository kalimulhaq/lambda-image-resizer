# Changelog

All notable changes to this project are documented in this file.

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
