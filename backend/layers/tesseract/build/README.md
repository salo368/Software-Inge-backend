# Receta de build de la Layer `tesseract`

Docker se usa aqui **solo como herramienta de build local**, igual que
`serverless-python-requirements` con `dockerizePip: true`. El artefacto que
realmente se despliega es el contenido zip de `../layer/` -- nunca una
imagen de contenedor en ejecucion (ver `docs/repo-structure.md` SS1).

## Por que no `dnf install tesseract`

Se intento primero `dnf install -y tesseract tesseract-langpack-spa` tanto
sobre la imagen minima de Lambda (`public.ecr.aws/lambda/python:3.12`,
`microdnf`) como sobre la imagen completa de Amazon Linux 2023
(`amazonlinux:2023`, `dnf` real). Las dos fallan igual:

```
error: No package matches 'tesseract'
```

Tesseract no esta empaquetado en los repos de AL2023 (ni como paquete base
ni en ninguna extension oficial). Confirmado tambien por busqueda externa:
no hay un Lambda Layer pre-compilado mantenido activamente para AL2023 /
Python 3.12 (los que existen -- `bweigel/aws-lambda-tesseract-layer`,
`shelfio/aws-lambda-tesseract` -- apuntan a Amazon Linux 2 / Node). Usar un
binario de terceros de procedencia no auditable en el pipeline de
documentos de un producto financiero tampoco era deseable. Se compila desde
el codigo fuente oficial en su lugar.

## Pasos (los dos Dockerfile de esta carpeta)

1. `Dockerfile.build` -- parte de `amazonlinux:2023` (no la imagen minima
   de Lambda, que no trae toolchain de compilacion), instala el grupo
   "Development Tools" + headers de libjpeg/libpng/zlib/libtiff/libwebp, y
   compila **leptonica 1.84.1** y **tesseract 5.4.1** desde sus tarballs
   oficiales (`github.com/DanBloomberg/leptonica`,
   `github.com/tesseract-ocr/tesseract`, ambos Apache-2.0), mas los
   `.traineddata` de `tessdata_fast` (eng + spa, mismo licenciamiento).
   Verificado end-to-end: `dnf install` de los headers resuelve sin
   problema (son librerias de imagen genericas, si estan en AL2023; solo
   tesseract/leptonica en si faltan).

2. `Dockerfile.package` -- parte de la imagen anterior, copia solo lo que
   el binario necesita en runtime a `/layer/{bin,lib,share/tessdata}` y lo
   empaqueta en `tesseract-layer.zip`. Punto critico: usa `cp -L`
   (dereferencia symlinks) en vez de `cp -P`, para que cada `.so` quede
   como un archivo real con el nombre SONAME exacto (`libtesseract.so.5`,
   no un symlink a `libtesseract.so.5.0.4`). Un primer intento con
   symlinks fallo con `file too short` al extraer el zip con
   `zipfile.extractall` de Python (no reconstituye el bit Unix de symlink
   de una entrada zip) -- quitar los symlinks de raiz evita depender de
   que el extractor de turno (el de AWS incluido, nunca verificado
   directamente) sepa interpretarlos.

## Como regenerar (requiere Docker local)

```bash
cd backend/layers/tesseract/build
docker build -f Dockerfile.build   -t tesseract-layer-build:local .
docker build -f Dockerfile.package -t tesseract-layer-package:local .
docker create --name extract tesseract-layer-package:local true
docker cp extract:/layer ../layer
docker rm extract
```

Esto sobreescribe `../layer/`. Commitear el resultado (es el artefacto que
`serverless.yml` de este bloque empaqueta via `layers.tesseract.path:
layer`).

## Verificacion end-to-end ya hecha (esta sesion)

Se verifico extrayendo el zip resultante dentro de un contenedor real
`public.ecr.aws/lambda/python:3.12` (no la imagen de build), exactamente
como Lambda monta una Layer en `/opt`, confirmando que `PATH` y
`LD_LIBRARY_PATH` del propio runtime de Lambda **ya incluyen** `/opt/bin` y
`/opt/lib` por defecto (no hace falta configurarlo a mano), y que
`pytesseract.image_to_string(img, lang="spa")` con
`TESSDATA_PREFIX=/opt/share/tessdata` extrae texto correctamente de una
imagen de prueba generada con PIL. Pendiente de verificar: el deploy real
contra AWS (requiere credenciales reales, fuera de este entorno de
desarrollo).
