# Lambda Image Resizer

[![GitHub Stars](https://img.shields.io/github/stars/kalimulhaq/lambda-image-resizer?style=flat-square)](https://github.com/kalimulhaq/lambda-image-resizer/stargazers)
[![CI](https://github.com/kalimulhaq/lambda-image-resizer/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/kalimulhaq/lambda-image-resizer/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.13%2B-3776AB?style=flat-square&logo=python&logoColor=white)](pyproject.toml)
[![AWS Lambda@Edge](https://img.shields.io/badge/AWS-Lambda%40Edge-FF9900?style=flat-square&logo=amazonaws&logoColor=white)](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/lambda-at-the-edge.html)
[![License](https://img.shields.io/github/license/kalimulhaq/lambda-image-resizer?style=flat-square)](LICENSE)

A generic, self-hosted on-the-fly image resizing and format-conversion service for any S3 + CloudFront setup, running as a Lambda@Edge `origin-request` function.

```
https://your-cdn.example.com/uploads/products/photo.jpg?w=500&h=333&f=webp
```

fits the image inside a 500×333 box (preserving aspect ratio, never cropping, never distorting, never upscaling past the source resolution), converts it to WebP, and caches the result at the CloudFront edge — indefinitely, since a given `(key, w, h, f)` combination always produces the same output.

## Why this exists

Most "serverless image resize" tutorials have the Lambda return the resized image bytes directly as its HTTP response. That works until an image is bigger than 1&nbsp;MB, at which point it breaks — Lambda@Edge caps generated responses at 1&nbsp;MB, and real photos routinely exceed that.

This project takes a different approach: on `origin-request`, the Lambda checks whether a resized derivative already exists in S3. If not, it computes one, uploads it to S3, and **rewrites the CloudFront request's URI** to point at that derivative key instead — it never returns image bytes itself. CloudFront then fetches the derivative from S3 exactly like any other object, through your existing origin. No response-size limit, no new CloudFront origin, no public-facing Lambda URL to secure.

## How to use it

This is how you can deploy to your own AWS account.

1. **Needs**: an existing S3+CloudFront setup, AWS CLI access, Python 3.13+pip.
2. **Build**: `./scripts/build.sh` — packages Pillow (fetched as a Lambda-compatible prebuilt wheel, no Docker needed) and the handler into `function.zip`.
3. **IAM**: create an execution role using `infra/trust-policy.example.json` (note it must trust *both* `lambda.amazonaws.com` and `edgelambda.amazonaws.com` — a Lambda@Edge-specific requirement) and `infra/s3-policy.example.json` (fill in your bucket name).
   The S3 policy only lets the function write under `resized/*` — if you change `X-Img-Resized-Prefix`, change that resource too.
4. **Deploy**: `FUNCTION_NAME=lambda-image-resizer ROLE_ARN=<your-role-arn> ./scripts/deploy.sh` — creates/updates the function **in `us-east-1`** (required for Lambda@Edge regardless of your bucket's region) and publishes a version (runs on `python3.13`, 30s timeout, 1024MB memory — override with `TIMEOUT=` / `MEMORY_SIZE=`). Lambda CPU scales with memory, so 1024MB resizes roughly twice as fast as 512MB for about the same cost.
5. **Wire into CloudFront**:
   - Add the three `X-Img-*` custom headers to your existing S3 origin (`infra/origin-custom-headers.example.json`).
   - Add the published version's ARN as an `origin-request` Lambda association on your cache behavior (`infra/lambda-function-association.example.json`).
   - Create a cache policy that forwards `w`/`h`/`f` as part of the cache key (`infra/cache-policy.example.json`) and assign it to that behavior — the default `CachingOptimized` managed policy forwards zero query strings, which would make every `w`/`h`/`f` combination collapse onto one cache entry.
   - Create a response headers policy (`infra/response-headers-policy.example.json`) and assign it to that behavior — see [Response headers](#response-headers).
   - Recommended: enable [Origin Shield](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/origin-shield.html) on the S3 origin, in the region closest to your bucket. The origin-request Lambda runs at the regional edge caches, so Origin Shield collapses requests from all of them into one — fewer Lambda invocations and more cache hits.
6. **Wait**: Lambda@Edge association changes propagate to edge locations over several minutes (often 15–30+) — longer than a typical CloudFront config change.

### How it's configured

Lambda@Edge doesn't support environment variables, so per-distribution configuration is passed via **CloudFront origin custom headers** instead — this is what makes one deployed function reusable across multiple, unrelated projects/buckets with zero code changes:

| Header | Meaning | Required |
|---|---|---|
| `X-Img-Bucket` | S3 bucket holding originals (and where derivatives get written) | Yes |
| `X-Img-Resized-Prefix` | Key prefix for derivatives | No — defaults to `resized` |
| `X-Img-Quality` | JPEG/WebP/AVIF save quality (1–100) | No — defaults to `82` |
| `X-Img-Max-Dimension` | Upper clamp for `w`/`h` (16–8192) | No — defaults to `4096` |
| `X-Img-Allowed-Sizes` | Comma-separated sizes, e.g. `320,640,960,1280,1920,2560`. Requested `w`/`h` are rounded **up** to the nearest one (or down to the largest) | No — off by default, **recommended in production** |
| `X-Img-Cache-Control` | `Cache-Control` stored on each derivative | No — defaults to `public, max-age=31536000, immutable` |

See `infra/origin-custom-headers.example.json`.

## Architecture

```
viewer request
      │
      ▼
CloudFront (existing cache behavior, existing S3 origin — unchanged)
      │
      ├─ origin-request Lambda@Edge trigger (this project)
      │       │
      │       ├─ no w/h/f, or ineligible source type → pass through unchanged
      │       ├─ derivative already in S3 → rewrite request URI, done
      │       └─ derivative missing → fetch original, resize/convert with
      │          Pillow, upload derivative to S3, rewrite request URI
      ▼
S3 (existing origin, existing bucket policy — unchanged) serves whichever
key the request now points at, exactly as it always has
```

No new CloudFront origin. No new cache behavior/path pattern required (though you can scope it to one if you prefer). No bucket policy change. No public-facing endpoint.

## Interface

| Param | Meaning | Notes |
|---|---|---|
| `w` | Target width in px | Optional. May be given alone. |
| `h` | Target height in px | Optional. May be given alone. |
| `f` | Output format | One of `webp`, `avif`, `jpeg`, `jpg`, `png`. Optional — omit to keep the source format. |

- `w` and `h` are independent: give one, both, or neither.
- Neither given → no resize (still useful for format-only conversion, or as a pure pass-through if `f` is also omitted).
- Both given → the image is scaled to fit *inside* that box (Pillow's "contain" semantics) — aspect ratio is always preserved, the image is never cropped, and it is never enlarged past its native resolution.
- **Every invalid or out-of-range input results in the original file being served, never an error.** Bad `w`/`h` values are clamped into a sane range (16–4096px by default, see `X-Img-Max-Dimension`) rather than rejected; an unsupported `f` is ignored; a request against a non-image file type is passed straight through without even being looked at.
- Photos are rotated upright according to their EXIF orientation. EXIF metadata (camera, GPS location) is stripped from derivatives; the embedded colour profile is kept.
- Originals over 25&nbsp;MB or 50 megapixels are served as-is rather than processed.
- `bmp` is readable as a source but not requestable via `f=` — `?f=bmp` is ignored like any unsupported format.

Only certain source file types are eligible for resizing at all — `jpg`, `jpeg`, `png`, `gif`, `webp`, `bmp`. Anything else (including `.svg`, which is vector and shouldn't be raster-resized) is passed straight through, regardless of query params.

## Usage examples

| Request | Result |
|---|---|
| `photo.jpg` | untouched |
| `photo.jpg?w=500` | resized to 500px wide, aspect preserved |
| `photo.jpg?w=500&h=333` | fit inside 500×333 box |
| `photo.jpg?f=webp` | format converted, no resize |
| `photo.jpg?w=99999` | clamped to max (4096px by default) |
| `logo.svg?w=500` | untouched — SVG never resized |

## Response headers

Each derivative is written to S3 with `Content-Type` and `Cache-Control: public, max-age=31536000, immutable` (configurable via `X-Img-Cache-Control`). Since a derivative's key never changes content, browsers and CloudFront can keep it for a year without revalidating.

S3 adds no security headers and leaks a few origin details, so attach `infra/response-headers-policy.example.json` to the cache behavior as a CloudFront response headers policy. It:

- adds `X-Content-Type-Options: nosniff`, `Strict-Transport-Security`, `Referrer-Policy`, `Cross-Origin-Resource-Policy: cross-origin` (so your site can embed images from the CDN hostname) and `Timing-Allow-Origin` (so real-user monitoring can see image load timings);
- adds `Cache-Control: public, max-age=86400` **only when the object has none** — this covers originals and derivatives created before v0.2.0;
- removes `Server`, `x-amz-server-side-encryption` and `x-amz-version-id`.

If you draw these images onto a `<canvas>` or fetch them from JavaScript, also add a `CorsConfig` to that policy.

### Limiting derivatives (recommended)

Every distinct `w`/`h`/`f` combination is a separate derivative: it costs one resize and is stored in S3 forever. With only clamping, anyone can request `w=100`, `w=101`, … and create thousands of derivatives per image. Setting `X-Img-Allowed-Sizes` caps that at a handful per image — pick the sizes your `srcset`s actually use.

## Cache invalidation

Derivatives are keyed by `(key, w, h, f)` only — not content. Overwriting an original at the same S3 key does **not** invalidate its derivatives; they'll keep being served, forever — and since they're sent with `immutable`, browsers won't re-check them either. If you replace images, use a new key/path rather than overwriting in place.

To regenerate every derivative (e.g. after upgrading, to pick up the new `Cache-Control` and encoder settings), delete the `resized/` prefix and invalidate `/*` in CloudFront.

## Development

Tests mock S3 via `moto` — no AWS credentials needed.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

ruff check .
ruff format --check .
mypy src/
pytest --cov=src
```

## Contributing

Please see [CONTRIBUTING](CONTRIBUTING.md) for details.

## Security

If you discover a security issue please email [kalim.dir@gmail.com](mailto:kalim.dir@gmail.com) rather than using the public issue tracker.

## Credits

- [Kalim ul Haq](https://github.com/kalimulhaq)
- [All Contributors](../../contributors)

## License

MIT — see [LICENSE](LICENSE).

## Support

If you find this project useful, consider supporting me on Ko-fi!

[![Support me on Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/kalimulhaq)
