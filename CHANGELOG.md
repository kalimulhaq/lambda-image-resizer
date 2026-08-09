# Changelog

All notable changes to this project are documented in this file.

## [0.1.0] - Unreleased

### Added
- Initial release: Lambda@Edge `origin-request` image resizer/format-converter backed by Pillow.
- `?w=&h=&f=` query interface — fit-inside resize (never crop, never distort, never upscale), with independent width/height and an output format allow-list.
- Config passed via CloudFront origin custom headers (`X-Img-Bucket`, `X-Img-Resized-Prefix`, `X-Img-Quality`) — no code changes needed to reuse across projects.
- Derivative persistence to S3, keyed deterministically, so a resized/converted variant is computed at most once.
- Every validation failure or unexpected error falls back to serving the original file — never a generated error response.
- Full pytest suite (pure-function unit tests + `moto`-backed integration tests), `ruff` + `mypy` clean, GitHub Actions CI and release workflows.
