#!/usr/bin/env bash
# Uploads the built frontend to S3 with proper Content-Type and Cache-Control per
# extension, then invalidates CloudFront. Avoids the aws-cli s3 sync MIME-guess
# bug on Windows (which serves .js as text/plain).
#
# Env:
#   BUCKET    - target S3 bucket (required)
#   DIST_ID   - CloudFront distribution id (required)
#   DIST_DIR  - built assets dir (default: frontend/dist/cdts-frontend/browser)

set -euo pipefail

DIST_DIR="${DIST_DIR:-frontend/dist/cdts-frontend/browser}"
: "${BUCKET:?BUCKET is required}"
: "${DIST_ID:?DIST_ID is required}"

log() { echo "$@" >&2; }

if [[ ! -d "${DIST_DIR}" ]]; then
  log "::error::DIST_DIR '${DIST_DIR}' does not exist. Run 'ng build' first."
  exit 1
fi

log "== s3://${BUCKET}/ <- ${DIST_DIR}/ (typed upload)"

# Hashed assets -> long immutable cache.
aws s3 cp "${DIST_DIR}/" "s3://${BUCKET}/" --recursive --exclude "*" --include "*.js" \
  --content-type "application/javascript" --cache-control "public, max-age=31536000, immutable" >/dev/null
aws s3 cp "${DIST_DIR}/" "s3://${BUCKET}/" --recursive --exclude "*" --include "*.css" \
  --content-type "text/css"               --cache-control "public, max-age=31536000, immutable" >/dev/null
aws s3 cp "${DIST_DIR}/" "s3://${BUCKET}/" --recursive --exclude "*" --include "*.svg" \
  --content-type "image/svg+xml"          --cache-control "public, max-age=31536000, immutable" >/dev/null 2>&1 || true
aws s3 cp "${DIST_DIR}/" "s3://${BUCKET}/" --recursive --exclude "*" --include "*.woff2" \
  --content-type "font/woff2"             --cache-control "public, max-age=31536000, immutable" >/dev/null 2>&1 || true
aws s3 cp "${DIST_DIR}/" "s3://${BUCKET}/" --recursive --exclude "*" --include "*.json" \
  --content-type "application/json"       --cache-control "public, max-age=31536000, immutable" >/dev/null 2>&1 || true

# Entry HTML -> no-cache so users always fetch the latest hash references.
aws s3 cp "${DIST_DIR}/" "s3://${BUCKET}/" --recursive --exclude "*" --include "*.html" \
  --content-type "text/html; charset=utf-8" --cache-control "no-cache" >/dev/null

# Favicon.
aws s3 cp "${DIST_DIR}/" "s3://${BUCKET}/" --recursive --exclude "*" --include "*.ico" \
  --content-type "image/x-icon" >/dev/null 2>&1 || true

# Cleanup stale files that no longer exist in the build. --size-only avoids
# re-uploads because we already set the metadata above.
log "== Removing stale objects"
aws s3 sync "${DIST_DIR}/" "s3://${BUCKET}/" --delete --size-only >/dev/null

log "== CloudFront invalidation"
INV_ID="$(aws cloudfront create-invalidation \
  --distribution-id "${DIST_ID}" --paths "/*" \
  --query 'Invalidation.Id' --output text)"
log "   invalidation: ${INV_ID}"
