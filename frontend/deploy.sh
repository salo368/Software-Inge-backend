#!/usr/bin/env bash
# Build del SPA + sync a S3.
# Requiere:
#   - Bucket ya provisionado (npm run deploy:frontend:infra)
#   - AWS creds cargadas (source scripts/load-aws-env.sh)
#   - npm install ya corrido en frontend/

set -euo pipefail
cd "$(dirname "$0")"

STAGE=${STAGE:-dev}

echo "[1/3] Leyendo bucket name desde CloudFormation..."
BUCKET=$(MSYS_NO_PATHCONV=1 aws cloudformation describe-stacks \
  --stack-name "cdts-frontend-${STAGE}" \
  --query 'Stacks[0].Outputs[?OutputKey==`BucketName`].OutputValue' \
  --output text)
URL=$(MSYS_NO_PATHCONV=1 aws cloudformation describe-stacks \
  --stack-name "cdts-frontend-${STAGE}" \
  --query 'Stacks[0].Outputs[?OutputKey==`WebsiteURL`].OutputValue' \
  --output text)

echo "    bucket: ${BUCKET}"

echo "[2/3] Build Vue (vite build)"
npm run build

echo "[3/3] Sync dist/ -> s3://${BUCKET}/"
MSYS_NO_PATHCONV=1 aws s3 sync dist/ "s3://${BUCKET}/" --delete

echo ""
echo "OK - SPA disponible en:"
echo "    ${URL}"
