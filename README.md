# lambda-image-resizer

A generic, self-hosted on-the-fly image resizing and format-conversion service for any S3 + CloudFront setup, running as a Lambda@Edge `origin-request` function.

```
https://your-cdn.example.com/uploads/products/photo.jpg?w=500&h=333&f=webp
```

fits the image inside a 500×333 box (preserving aspect ratio, never cropping, never distorting, never upscaling past the source resolution), converts it to WebP, and caches the result at the CloudFront edge — indefinitely, since a given `(key, w, h, f)` combination always produces the same output.

## Why this exists

Most "serverless image resize" tutorials have the Lambda return the resized image bytes directly as its HTTP response. That works until an image is bigger than 1&nbsp;MB, at which point it breaks — Lambda@Edge caps generated responses at 1&nbsp;MB, and real photos routinely exceed that.

This project takes a different approach: on `origin-request`, the Lambda checks whether a resized derivative already exists in S3. If not, it computes one, uploads it to S3, and **rewrites the CloudFront request's URI** to point at that derivative key instead — it never returns image bytes itself. CloudFront then fetches the derivative from S3 exactly like any other object, through your existing origin. No response-size limit, no new CloudFront origin, no public-facing Lambda URL to secure.

## Interface

| Param | Meaning | Notes |
|---|---|---|
| `w` | Target width in px | Optional. May be given alone. |
| `h` | Target height in px | Optional. May be given alone. |
| `f` | Output format | One of `webp`, `avif`, `jpeg`, `jpg`, `png`. Optional — omit to keep the source format. |

- `w` and `h` are independent: give one, both, or neither.
- Neither given → no resize (still useful for format-only conversion, or as a pure pass-through if `f` is also omitted).
- Both given → the image is scaled to fit *inside* that box (Pillow's "contain" semantics) — aspect ratio is always preserved, the image is never cropped, and it is never enlarged past its native resolution.
- **Every invalid or out-of-range input results in the original file being served, never an error.** Bad `w`/`h` values are clamped into a sane range (16–2400px by default) rather than rejected; an unsupported `f` is ignored; a request against a non-image file type is passed straight through without even being looked at.

Only certain source file types are eligible for resizing at all — `jpg`, `jpeg`, `png`, `gif`, `webp`, `bmp`. Anything else (including `.svg`, which is vector and shouldn't be raster-resized) is passed straight through, regardless of query params.

## How it's configured

Lambda@Edge doesn't support environment variables, so per-distribution configuration is passed via **CloudFront origin custom headers** instead — this is what makes one deployed function reusable across multiple, unrelated projects/buckets with zero code changes:

| Header | Meaning | Required |
|---|---|---|
| `X-Img-Bucket` | S3 bucket holding originals (and where derivatives get written) | Yes |
| `X-Img-Resized-Prefix` | Key prefix for derivatives | No — defaults to `resized` |
| `X-Img-Quality` | JPEG/WebP save quality (1–100) | No — defaults to `82` |

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

## Deploying (to your own AWS account)

1. **Build**: `./scripts/build.sh` — packages Pillow (fetched as a Lambda-compatible prebuilt wheel, no Docker needed) and the handler into `function.zip`.
2. **IAM**: create an execution role using `infra/trust-policy.example.json` (note it must trust *both* `lambda.amazonaws.com` and `edgelambda.amazonaws.com` — a Lambda@Edge-specific requirement) and `infra/s3-policy.example.json` (fill in your bucket name).
3. **Deploy**: `FUNCTION_NAME=lambda-image-resizer ROLE_ARN=<your-role-arn> ./scripts/deploy.sh` — creates/updates the function **in `us-east-1`** (required for Lambda@Edge regardless of your bucket's region) and publishes a version.
4. **Wire into CloudFront**:
   - Add the three `X-Img-*` custom headers to your existing S3 origin (`infra/origin-custom-headers.example.json`).
   - Add the published version's ARN as an `origin-request` Lambda association on your cache behavior (`infra/lambda-function-association.example.json`).
   - Create a cache policy that forwards `w`/`h`/`f` as part of the cache key (`infra/cache-policy.example.json`) and assign it to that behavior — the default `CachingOptimized` managed policy forwards zero query strings, which would make every `w`/`h`/`f` combination collapse onto one cache entry.
5. **Wait**: Lambda@Edge association changes propagate to edge locations over several minutes (often 15–30+) — longer than a typical CloudFront config change.

## Development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

ruff check .
ruff format --check .
mypy src/
pytest --cov=src
```

## License

MIT — see [LICENSE](LICENSE).
