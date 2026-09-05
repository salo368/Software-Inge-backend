#!/usr/bin/env bash
# Build del SPA + sync a S3.
# Requiere:
#   - Bucket ya provisionado (npm run deploy:frontend:infra)
#   - AWS creds cargadas (source scripts/load-aws-env.sh)
#   - npm install ya corrido en frontend/

set -euo pipefail
cd "$(dirname "$0")"

STAGE=${STAGE:-dev}

echo "[1/5] Leyendo bucket name desde CloudFormation..."
BUCKET=$(MSYS_NO_PATHCONV=1 aws cloudformation describe-stacks \
  --stack-name "cdts-frontend-${STAGE}" \
  --query 'Stacks[0].Outputs[?OutputKey==`BucketName`].OutputValue' \
  --output text)
URL=$(MSYS_NO_PATHCONV=1 aws cloudformation describe-stacks \
  --stack-name "cdts-frontend-${STAGE}" \
  --query 'Stacks[0].Outputs[?OutputKey==`WebsiteURL`].OutputValue' \
  --output text)

echo "    bucket: ${BUCKET}"

echo "[2/5] Build Vue (vite build)"
npm run build

# En Windows los MIME de mimetypes son basura. Subimos por tipo con content-type explicito
# para que los browsers no rechacen los <script type=\"module\"> ni el CSS.

echo "[3/5] Sync base (html/imagenes/otros) + --delete"
MSYS_NO_PATHCONV=1 aws s3 sync dist/ "s3://${BUCKET}/" --delete \
  --exclude "*.js" --exclude "*.css" --exclude "*.map"

echo "[4/5] Upload JS con Content-Type: application/javascript"
MSYS_NO_PATHCONV=1 aws s3 cp dist/ "s3://${BUCKET}/" --recursive \
  --exclude "*" --include "*.js" \
  --content-type "application/javascript" \
  --metadata-directive REPLACE

echo "[5/5] Upload CSS con Content-Type: text/css"
MSYS_NO_PATHCONV=1 aws s3 cp dist/ "s3://${BUCKET}/" --recursive \
  --exclude "*" --include "*.css" \
  --content-type "text/css" \
  --metadata-directive REPLACE

echo ""
echo "OK - SPA disponible en:"
echo "    ${URL}"
