#!/usr/bin/env bash
#
# scripts/bootstrap-signatures-v2.sh
#
# One-time bootstrap of the SSM parameters that the signatures service
# (v2) needs before it can serve traffic in a given stage. Safe to
# re-run: every step checks whether the parameter already exists and
# asks for confirmation before overwriting.
#
# What it does, in order:
#
#   1. Mock CA root certificate + private key (SecureString):
#          /cdts/{STAGE}/mock-ca/root/cert-pem
#          /cdts/{STAGE}/mock-ca/root/private-key-pem
#      Generated on-the-fly with openssl in a temp dir; files are
#      shredded at the end. The `-pem` suffix is required by
#      utils/mock_ca.py -- do not shorten.
#
#   2. Signatures service key (SecureString):
#          /cdts/{STAGE}/signatures/service-key
#      Generated with `openssl rand -hex 32`.
#
#   3. Processes HTTP API base URL (String):
#          /cdts/{STAGE}/processes-api/url
#      Read from the `HttpApiId` output of stack cdts-{STAGE}-processes.
#      Skipped if the stack doesn't exist yet.
#
# Requirements:
#
#   * bash (git bash on Windows works)
#   * awscli v2 with credentials that have ssm:PutParameter +
#     kms:Encrypt on the /cdts/* prefix (i.e. NOT the deploy role,
#     which is scoped to Lambda/IAM/API Gateway). Typically an admin
#     IAM user for the account.
#   * openssl >= 1.1
#
# Usage:
#
#   bash scripts/bootstrap-signatures-v2.sh dev
#   bash scripts/bootstrap-signatures-v2.sh pro
#
# The script never prints the actual secret values to stdout. Only
# metadata (Name / ARN / LastModifiedDate) is echoed.

set -euo pipefail

# `aws_ssm` wraps `aws ssm ...` calls so that MSYS/git-bash on Windows
# does NOT rewrite SSM parameter names such as "/cdts/dev/mock-ca/root/cert-pem"
# into Windows paths ("C:/Program Files/Git/cdts/dev/..."), which the
# AWS API rejects with "Parameter name must be a fully qualified name".
#
# We deliberately do NOT export MSYS_NO_PATHCONV=1 globally, because
# `mktemp -d` returns unix-style paths ("/tmp/cdts-mock-ca-XXX") which
# openssl (native Windows binary) can only consume once MSYS
# re-writes them to Windows form. Turning conversion off globally
# breaks openssl.
aws_ssm() {
  MSYS_NO_PATHCONV=1 aws ssm "$@"
}

# --------------------------------------------------------------------------- #
# Args + preflight
# --------------------------------------------------------------------------- #
STAGE="${1:-}"
if [[ -z "$STAGE" ]]; then
  echo "usage: $0 <stage>    # stage in {dev, pro}"
  exit 2
fi
if [[ "$STAGE" != "dev" && "$STAGE" != "pro" ]]; then
  echo "error: stage must be 'dev' or 'pro' (got '$STAGE')"
  exit 2
fi

REGION="${AWS_REGION:-us-east-1}"

# Sanity check: creds must be present and NOT be the deploy role
# (deploy role can't PutParameter).
if ! aws sts get-caller-identity >/dev/null 2>&1; then
  echo "error: no AWS credentials configured. run 'aws configure' first."
  exit 3
fi
CALLER_ARN="$(aws sts get-caller-identity --query Arn --output text)"
if [[ "$CALLER_ARN" == *"github-actions-"*"-deployer"* ]]; then
  echo "error: you're running as the deploy role ($CALLER_ARN)."
  echo "       that role has no ssm:PutParameter permission."
  echo "       switch to an admin/bootstrap identity and re-run."
  exit 4
fi

echo "==============================================================="
echo " Bootstrap signatures v2 SSM params"
echo "   stage:  $STAGE"
echo "   region: $REGION"
echo "   caller: $CALLER_ARN"
echo "==============================================================="
echo

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
param_exists() {
  aws_ssm get-parameter --name "$1" --region "$REGION" >/dev/null 2>&1
}

confirm_overwrite() {
  # $1 = param name
  echo
  read -rp "  param '$1' already exists. OVERWRITE? [y/N] " ans
  case "$ans" in
    y|Y|yes|YES) return 0 ;;
    *)           echo "  -> skipping."; return 1 ;;
  esac
}

put_secure_string() {
  # $1 = name, $2 = value, $3 = description
  local extra=()
  if param_exists "$1"; then
    if ! confirm_overwrite "$1"; then
      return 0
    fi
    extra+=(--overwrite)
  fi
  aws_ssm put-parameter \
    --region "$REGION" \
    --name "$1" \
    --type SecureString \
    --value "$2" \
    --description "$3" \
    "${extra[@]}" \
    --query '{Name: `'"$1"'`, Tier: Tier, Version: Version}' \
    --output table
}

put_plain_string() {
  # $1 = name, $2 = value, $3 = description
  local extra=()
  if param_exists "$1"; then
    if ! confirm_overwrite "$1"; then
      return 0
    fi
    extra+=(--overwrite)
  fi
  aws_ssm put-parameter \
    --region "$REGION" \
    --name "$1" \
    --type String \
    --value "$2" \
    --description "$3" \
    "${extra[@]}" \
    --query '{Name: `'"$1"'`, Tier: Tier, Version: Version}' \
    --output table
}

# --------------------------------------------------------------------------- #
# Step 1: mock CA root cert + key
# --------------------------------------------------------------------------- #
echo "--- Step 1: mock CA root cert + key ------------------------------------"
# NAMING NOTE: parameters end in `-pem` because utils/mock_ca.py and the
# IAM policy in services/signatures/serverless.yml both hard-code those
# suffixes. Do NOT rename to shorter forms unless you also update the
# lambda code, the IAM Resource ARNs, and every unit test that pins
# these strings.
CA_PARAM_CERT="/cdts/$STAGE/mock-ca/root/cert-pem"
CA_PARAM_KEY="/cdts/$STAGE/mock-ca/root/private-key-pem"

TMPDIR="$(mktemp -d -t cdts-mock-ca-XXXXXX)"
trap 'rm -rf "$TMPDIR"' EXIT

CA_KEY="$TMPDIR/root.key"
CA_CRT="$TMPDIR/root.crt"
CA_CONF="$TMPDIR/openssl.cnf"

echo "  Generating RSA-2048 root key..."
openssl genrsa -out "$CA_KEY" 2048 2>/dev/null

# Config as a real file rather than process substitution, and with the
# DN embedded inline (`prompt = no`) instead of a separate `-subj` flag.
# Two portability reasons:
#
#   * The native Windows openssl (Win-OpenSSL / MSYS / git-bash) cannot
#     resolve `<(cat <<EOF)` because it dereferences /proc/<pid>/fd/N,
#     which does not exist outside real Linux.
#   * git-bash rewrites the leading '/' of a `-subj "/C=CO/..."` value
#     into a Windows path ("C:/Program Files/Git/C=CO/..."), which
#     openssl then rejects. Toggling MSYS_NO_PATHCONV=1 fixes the -subj
#     but simultaneously breaks the -config path resolution.
#
# Passing the DN inside the same config file sidesteps both.
cat > "$CA_CONF" <<EOF
[req]
distinguished_name = dn
prompt             = no
[dn]
C  = CO
O  = CDTS Academico
OU = Mock CA
CN = CDTS Mock Root CA $STAGE
[v3_ca]
basicConstraints     = critical, CA:TRUE, pathlen:0
keyUsage             = critical, keyCertSign, cRLSign
subjectKeyIdentifier = hash
EOF

echo "  Generating 10-year self-signed root cert..."
openssl req -new -x509 -sha256 -days 3650 \
  -key "$CA_KEY" \
  -out "$CA_CRT" \
  -extensions v3_ca \
  -config "$CA_CONF" 2>/dev/null

echo "  Uploading root cert to SSM ($CA_PARAM_CERT)..."
put_secure_string \
  "$CA_PARAM_CERT" \
  "$(cat "$CA_CRT")" \
  "Mock CA root certificate for signatures v2 (bootstrap: $(date -u +%Y-%m-%dT%H:%M:%SZ))."

echo "  Uploading root key to SSM ($CA_PARAM_KEY)..."
put_secure_string \
  "$CA_PARAM_KEY" \
  "$(cat "$CA_KEY")" \
  "Mock CA root private key. Do not extract."

echo "  Local artifacts stored in $TMPDIR; will be removed on exit."
echo

# --------------------------------------------------------------------------- #
# Step 2: signatures service key
# --------------------------------------------------------------------------- #
echo "--- Step 2: signatures M2M service key ---------------------------------"
SVC_KEY_PARAM="/cdts/$STAGE/signatures/service-key"
SVC_KEY_VALUE="$(openssl rand -hex 32)"

echo "  Uploading service key to SSM ($SVC_KEY_PARAM)..."
put_secure_string \
  "$SVC_KEY_PARAM" \
  "$SVC_KEY_VALUE" \
  "M2M shared secret for POST /signatures (X-Service-Key header). Callers: processes.signature_bridge."
unset SVC_KEY_VALUE
echo

# --------------------------------------------------------------------------- #
# Step 3: processes HTTP API URL
# --------------------------------------------------------------------------- #
echo "--- Step 3: processes HTTP API base URL --------------------------------"
API_URL_PARAM="/cdts/$STAGE/processes-api/url"
STACK="cdts-$STAGE-processes"

if ! aws cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" >/dev/null 2>&1; then
  echo "  Stack '$STACK' does not exist yet; skipping."
  echo "  Re-run this script after 'processes' has been deployed at least once,"
  echo "  or bootstrap the URL manually per docs/signatures-v2.md \u00a78.4."
else
  # Serverless Framework generates the HttpApi output as `HttpApiUrl`
  # (the full URL) OR `HttpApiId` (just the id). Try URL first, fall
  # back to id.
  API_URL="$(aws cloudformation describe-stacks \
    --stack-name "$STACK" \
    --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='HttpApiUrl'].OutputValue" \
    --output text 2>/dev/null || true)"

  if [[ -z "$API_URL" || "$API_URL" == "None" ]]; then
    API_ID="$(aws cloudformation describe-stacks \
      --stack-name "$STACK" \
      --region "$REGION" \
      --query "Stacks[0].Outputs[?OutputKey=='HttpApiId'].OutputValue" \
      --output text 2>/dev/null || true)"
    if [[ -z "$API_ID" || "$API_ID" == "None" ]]; then
      echo "  error: stack '$STACK' has no HttpApiUrl / HttpApiId output."
      echo "         resolve manually via docs/signatures-v2.md \u00a78.4."
      exit 5
    fi
    API_URL="https://${API_ID}.execute-api.${REGION}.amazonaws.com"
  else
    # Strip any trailing slash so signature_bridge doesn't build "//path".
    API_URL="${API_URL%/}"
  fi

  echo "  Detected API base URL: $API_URL"
  echo "  Uploading to SSM ($API_URL_PARAM)..."
  put_plain_string \
    "$API_URL_PARAM" \
    "$API_URL" \
    "Base URL of the processes HTTP API (stage $STAGE). Read by processes/signature_bridge to build the callback URL."
fi

# --------------------------------------------------------------------------- #
# Summary
# --------------------------------------------------------------------------- #
echo
echo "==============================================================="
echo " Done."
echo
echo " Sanity check (no values printed, only ARNs + last-modified):"
echo "==============================================================="
for p in "$CA_PARAM_CERT" "$CA_PARAM_KEY" "$SVC_KEY_PARAM" "$API_URL_PARAM"; do
  if param_exists "$p"; then
    aws_ssm get-parameter --name "$p" --region "$REGION" \
      --query "Parameter.{Name: Name, Type: Type, Version: Version, LastModified: LastModifiedDate}" \
      --output table
  else
    echo "  (missing) $p"
  fi
done
