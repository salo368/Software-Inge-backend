#!/usr/bin/env bash
# Empaqueta la suite de pruebas (tests/) dentro del servicio para que la
# Lambda runner pueda ejecutarla con pytest.
set -euo pipefail
cd "$(dirname "$0")"

rm -rf bundle
mkdir -p bundle/services/digital_signature/src/validate
cp -r ../../tests bundle/tests
rm -f bundle/tests/report.html
cp ../../services/digital_signature/src/validate/handler.py \
   bundle/services/digital_signature/src/validate/handler.py

echo "OK - bundle listo"
