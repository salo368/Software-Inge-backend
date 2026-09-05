#!/usr/bin/env bash
# Construye el contenido de la layer:
#   1. Instala requirements.txt en python/  (wheels manylinux aarch64 para Lambda ARM64)
#   2. Copia ../../utils/ a python/utils/
#
# Uso:
#   cd layers/shared
#   ./build.sh
#
# Requisitos:
#   - Python 3.11 con pip
#   - Wheels manylinux2014_aarch64 disponibles en PyPI (bcrypt, etc)

set -euo pipefail
cd "$(dirname "$0")"

echo "[1/3] Limpiando python/"
rm -rf python
mkdir -p python

echo "[2/3] Instalando deps para linux/arm64..."
pip install \
  --platform manylinux2014_aarch64 \
  --target python \
  --implementation cp \
  --python-version 3.11 \
  --only-binary=:all: \
  --upgrade \
  -r requirements.txt

echo "[3/3] Copiando ../../utils -> python/utils"
cp -r ../../utils python/utils

# Limpieza: cache de python (reduce peso)
find python -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

SIZE=$(du -sh python | cut -f1)
echo ""
echo "OK - Layer lista ($SIZE)"
