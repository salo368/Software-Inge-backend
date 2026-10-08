# Imagen de contenedor SOLO para src/workers/on_upload -- es la única
# función que necesita el binario `tesseract` real (OCR), que un paquete
# zip estándar no puede traer (pytesseract es solo el wrapper de Python,
# ver domain/adapters/tesseract_adapter.py). Las otras cuatro funciones de
# este servicio (upload_url, get_status, check_reuse, confirm_reuse) siguen
# empaquetadas como zip normal vía serverless-python-requirements -- no
# necesitan Tesseract y no hay razón para pagar el costo de arranque en
# frío de una imagen más pesada.
#
# NOTA PARA QUIEN CONSTRUYA ESTA IMAGEN POR PRIMERA VEZ: los nombres de
# paquete `tesseract` / `tesseract-langpack-spa` son los esperados para
# Amazon Linux 2023 (base de esta imagen oficial de Lambda), pero no se
# pudieron verificar en este entorno de trabajo por falta de acceso a
# internet y de un daemon Docker disponible. Si `dnf install` falla con
# "No match for argument", confirmar el nombre exacto del paquete con
# `dnf search tesseract` dentro de un contenedor `public.ecr.aws/lambda/
# python:3.12` interactivo antes de cambiar de estrategia.
FROM public.ecr.aws/lambda/python:3.12

RUN dnf install -y tesseract tesseract-langpack-spa \
    && dnf clean all \
    && rm -rf /var/cache/dnf

# El resto de dependencias Python del servicio (sqlalchemy, pg8000,
# pytesseract, Pillow, rapidfuzz) -- mismo requirements.txt que usa el
# paquete zip de las otras cuatro funciones, para que las dos formas de
# empaquetado nunca diverjan en versiones.
COPY requirements.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt -t ${LAMBDA_TASK_ROOT}

# libs/ se copia aparte porque functions.js la mirror-copia desde
# backend/libs/ al desplegar el paquete zip (ver ese script); para la
# imagen, serverless-compose la deja en ./libs/ del contexto de build de
# la misma forma antes de invocar `docker build`, así que esta línea
# asume que ya está ahí -- no la genera este Dockerfile.
COPY src/ ${LAMBDA_TASK_ROOT}/src/
COPY domain/ ${LAMBDA_TASK_ROOT}/domain/
COPY libs/ ${LAMBDA_TASK_ROOT}/libs/

# Igual que el filtro `package.patterns` del paquete zip (ver
# serverless.yml): las pruebas colocalizadas no viajan a producción.
RUN find ${LAMBDA_TASK_ROOT} -name "test.py" -delete \
    && find ${LAMBDA_TASK_ROOT} -name "integration.py" -delete \
    && find ${LAMBDA_TASK_ROOT} -name "conftest.py" -delete \
    && find ${LAMBDA_TASK_ROOT} -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

CMD ["src.workers.on_upload.handler.handler"]
