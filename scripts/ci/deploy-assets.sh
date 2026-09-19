#!/usr/bin/env bash
# Syncs backend/platform/assets/files/ to the S3 assets bucket for the given
# stage, with explicit content types per extension. Assumes `sls deploy` was
# already run and the bucket exists.
#
# Env:
#   STAGE   - dev or pro (required)

set -euo pipefail

: "${STAGE:?STAGE is required (dev|pro)}"

SRC_DIR="backend/platform/assets/files"
BUCKET="cdts-${STAGE}-assets"

log() { echo "$@" >&2; }

if [[ ! -d "${SRC_DIR}" ]]; then
  log "::error::SRC_DIR '${SRC_DIR}' does not exist."
  exit 1
fi

log "== s3://${BUCKET}/ <- ${SRC_DIR}/ (typed upload)"

# PNG.
aws s3 cp "${SRC_DIR}/" "s3://${BUCKET}/" --recursive --exclude "*" --include "*.png" \
  --content-type "image/png" --cache-control "public, max-age=86400" >/dev/null 2>&1 || true

# JPG/JPEG.
aws s3 cp "${SRC_DIR}/" "s3://${BUCKET}/" --recursive --exclude "*" --include "*.jpg" \
  --content-type "image/jpeg" --cache-control "public, max-age=86400" >/dev/null 2>&1 || true
aws s3 cp "${SRC_DIR}/" "s3://${BUCKET}/" --recursive --exclude "*" --include "*.jpeg" \
  --content-type "image/jpeg" --cache-control "public, max-age=86400" >/dev/null 2>&1 || true

# SVG.
aws s3 cp "${SRC_DIR}/" "s3://${BUCKET}/" --recursive --exclude "*" --include "*.svg" \
  --content-type "image/svg+xml" --cache-control "public, max-age=86400" >/dev/null 2>&1 || true

# WEBP.
aws s3 cp "${SRC_DIR}/" "s3://${BUCKET}/" --recursive --exclude "*" --include "*.webp" \
  --content-type "image/webp" --cache-control "public, max-age=86400" >/dev/null 2>&1 || true

# Remove stale objects, keep metadata already set above.
log "== Removing stale objects"
aws s3 sync "${SRC_DIR}/" "s3://${BUCKET}/" --delete --size-only >/dev/null

log "== done: https://${BUCKET}.s3.amazonaws.com/"
