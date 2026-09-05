#!/usr/bin/env bash
# Build del SPA de firma + sync a S3.
# Requiere bucket provisionado (npm run deploy:firma:infra) y AWS creds cargadas.

set -euo pipefail
cd "$(dirname "$0")"

STAGE=${STAGE:-dev}

echo "[1/5] Leyendo bucket name desde CloudFormation..."
BUCKET=$(MSYS_NO_PATHCONV=1 aws cloudformation describe-stacks \
  --stack-name "cdts-firma-${STAGE}" \
  --query 'Stacks[0].Outputs[?OutputKey==`BucketName`].OutputValue' \
  --output text)
URL=$(MSYS_NO_PATHCONV=1 aws cloudformation describe-stacks \
  --stack-name "cdts-firma-${STAGE}" \
  --query 'Stacks[0].Outputs[?OutputKey==`WebsiteURL`].OutputValue' \
  --output text)

echo "    bucket: ${BUCKET}"

echo "[2/5] Build Vue (vite build)"
npm run build

echo "[3/5] Sync base (html/otros) + --delete"
MSYS_NO_PATHCONV=1 aws s3 sync dist/ "s3://${BUCKET}/" --delete \
  --exclude "*.js" --exclude "*.mjs" --exclude "*.css" --exclude "*.map"

echo "[4/5] Upload JS/MJS con Content-Type: application/javascript"
MSYS_NO_PATHCONV=1 aws s3 cp dist/ "s3://${BUCKET}/" --recursive \
  --exclude "*" --include "*.js" --include "*.mjs" \
  --content-type "application/javascript" \
  --metadata-directive REPLACE

echo "[5/5] Upload CSS con Content-Type: text/css"
MSYS_NO_PATHCONV=1 aws s3 cp dist/ "s3://${BUCKET}/" --recursive \
  --exclude "*" --include "*.css" \
  --content-type "text/css" \
  --metadata-directive REPLACE

echo ""
echo "OK - Front de firma disponible en:"
echo "    ${URL}"
