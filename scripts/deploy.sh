#!/usr/bin/env bash
# Example deploy script: creates (or updates) the Lambda function and
# publishes a new version. This is NOT run by CI — deployment is a
# per-consumer action against your own AWS account. Copy/adapt as needed.
#
# Required env vars:
#   FUNCTION_NAME   - e.g. lambda-image-resizer
#   ROLE_ARN        - the execution role's ARN (see infra/trust-policy.example.json
#                      and infra/s3-policy.example.json)
#   AWS_PROFILE     - optional, defaults to your default profile
#   MEMORY_SIZE     - optional, MB, defaults to 1024 (Lambda CPU scales with
#                      memory, so this roughly halves resize time vs 512)
#   TIMEOUT         - optional, seconds, defaults to 30 (the origin-request max)
#
# Usage:
#   ./scripts/build.sh
#   FUNCTION_NAME=lambda-image-resizer ROLE_ARN=arn:aws:iam::123456789012:role/lambda-image-resizer-role \
#     ./scripts/deploy.sh
set -euo pipefail

cd "$(dirname "$0")/.."

: "${FUNCTION_NAME:?Set FUNCTION_NAME}"
: "${ROLE_ARN:?Set ROLE_ARN}"

if [ ! -f function.zip ]; then
  echo "function.zip not found — run scripts/build.sh first." >&2
  exit 1
fi

# Lambda@Edge functions MUST be created/updated in us-east-1, regardless of
# where they'll eventually run at edge locations.
REGION="us-east-1"
MEMORY_SIZE="${MEMORY_SIZE:-1024}"
TIMEOUT="${TIMEOUT:-30}"

if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" >/dev/null 2>&1; then
  echo "Updating existing function $FUNCTION_NAME..."
  aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file fileb://function.zip \
    --region "$REGION" >/dev/null
  aws lambda wait function-updated-v2 --function-name "$FUNCTION_NAME" --region "$REGION"
  aws lambda update-function-configuration \
    --function-name "$FUNCTION_NAME" \
    --timeout "$TIMEOUT" \
    --memory-size "$MEMORY_SIZE" \
    --region "$REGION" >/dev/null
  aws lambda wait function-updated-v2 --function-name "$FUNCTION_NAME" --region "$REGION"
else
  echo "Creating function $FUNCTION_NAME..."
  aws lambda create-function \
    --function-name "$FUNCTION_NAME" \
    --runtime python3.13 \
    --handler lambda_image_resizer.handler.handler \
    --role "$ROLE_ARN" \
    --zip-file fileb://function.zip \
    --timeout "$TIMEOUT" \
    --memory-size "$MEMORY_SIZE" \
    --region "$REGION" >/dev/null
  aws lambda wait function-active-v2 --function-name "$FUNCTION_NAME" --region "$REGION"
fi

echo "Publishing new version..."
VERSION_ARN=$(aws lambda publish-version \
  --function-name "$FUNCTION_NAME" \
  --region "$REGION" \
  --query FunctionArn \
  --output text)

echo "Published: $VERSION_ARN"
echo "Use this exact ARN (including the version number) in your CloudFront"
echo "distribution's LambdaFunctionAssociations — see"
echo "infra/lambda-function-association.example.json."
