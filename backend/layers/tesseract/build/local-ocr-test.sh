#!/usr/bin/env bash
# Prueba local, real, del Lambda Layer de Tesseract (backend/layers/tesseract)
# contra el codigo real de domain/adapters/tesseract_adapter.py.
#
# Corre dentro de la MISMA imagen base que usa el Lambda real en AWS
# (public.ecr.aws/lambda/python:3.12). Esa imagen ya trae /opt/bin en PATH
# y /opt/lib en LD_LIBRARY_PATH por defecto -- es como AWS prepara CUALQUIER
# funcion para que pueda referenciar una Layer, lo verificamos con
# `docker run ... echo $PATH` antes de escribir este script. Por eso basta
# con montar el contenido de la Layer en /opt: no hace falta tocar el PATH
# a mano para replicar el comportamiento real.
#
# No requiere credenciales AWS ni un deploy real -- es el proxy local mas
# fiel disponible a "el Lambda on_upload desplegado puede leer un documento".
#
# Uso:
#   bash backend/layers/tesseract/build/local-ocr-test.sh
#
# Requiere: Docker Desktop corriendo.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

LAYER_DIR="${BACKEND_DIR}/layers/tesseract/layer"
DOCUMENTS_DIR="${BACKEND_DIR}/services/documents"

echo "Layer:     ${LAYER_DIR}"
echo "Documents: ${DOCUMENTS_DIR}"
echo

# MSYS_NO_PATHCONV evita que Git Bash en Windows reescriba las rutas tipo
# /opt o /var/task como si fueran rutas de Windows antes de pasarlas a docker.
MSYS_NO_PATHCONV=1 docker run --rm \
  --entrypoint /bin/sh \
  -v "${LAYER_DIR}:/opt:ro" \
  -v "${DOCUMENTS_DIR}/domain:/var/task/domain:ro" \
  -v "${SCRIPT_DIR}/ocr_smoke_test.py:/tmp/ocr_smoke_test.py:ro" \
  public.ecr.aws/lambda/python:3.12 \
  -c "
    set -e
    pip install --quiet pytesseract==0.3.13 Pillow==10.4.0 &&
    TESSDATA_PREFIX=/opt/share/tessdata python3 /tmp/ocr_smoke_test.py
  "
