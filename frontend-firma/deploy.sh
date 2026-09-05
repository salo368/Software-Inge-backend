#!/usr/bin/env bash
# Build del SPA de firma + sync a S3.
# Requiere bucket provisionado (npm run deploy:firma:infra) y AWS creds cargadas.

set -euo pipefail
cd "$(dirname "$0")"

STAGE=${STAGE:-dev}

echo "[1/6] Leyendo bucket name desde CloudFormation..."
BUCKET=$(MSYS_NO_PATHCONV=1 aws cloudformation describe-stacks \
  --stack-name "cdts-firma-${STAGE}" \
  --query 'Stacks[0].Outputs[?OutputKey==`BucketName`].OutputValue' \
  --output text)
CDN_DOMAIN=$(MSYS_NO_PATHCONV=1 aws cloudformation describe-stacks \
  --stack-name "cdts-firma-${STAGE}" \
  --query 'Stacks[0].Outputs[?OutputKey==`CloudFrontDomain`].OutputValue' \
  --output text)
CDN_ID=$(MSYS_NO_PATHCONV=1 aws cloudformation describe-stacks \
  --stack-name "cdts-firma-${STAGE}" \
  --query 'Stacks[0].Outputs[?OutputKey==`CloudFrontId`].OutputValue' \
  --output text)

echo "    bucket: ${BUCKET}"

echo "[2/6] Build Vue (vite build)"
npm run build

echo "[3/6] Sync base (html/otros) + --delete"
MSYS_NO_PATHCONV=1 aws s3 sync dist/ "s3://${BUCKET}/" --delete \
  --exclude "*.js" --exclude "*.mjs" --exclude "*.css" --exclude "*.map"

echo "[4/6] Upload JS/MJS con Content-Type: application/javascript"
MSYS_NO_PATHCONV=1 aws s3 cp dist/ "s3://${BUCKET}/" --recursive \
  --exclude "*" --include "*.js" --include "*.mjs" \
  --content-type "application/javascript" \
  --metadata-directive REPLACE

echo "[5/6] Upload CSS con Content-Type: text/css"
MSYS_NO_PATHCONV=1 aws s3 cp dist/ "s3://${BUCKET}/" --recursive \
  --exclude "*" --include "*.css" \
  --content-type "text/css" \
  --metadata-directive REPLACE

echo "[6/6] Invalidando cache de CloudFront"
MSYS_NO_PATHCONV=1 aws cloudfront create-invalidation \
  --distribution-id "${CDN_ID}" --paths "/*" --query 'Invalidation.Id' --output text

echo ""
echo "OK - Front de firma disponible en:"
echo "    https://${CDN_DOMAIN}"
