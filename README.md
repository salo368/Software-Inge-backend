# CDTS

Serverless multi-servicio en AWS (Lambda + API Gateway HTTP API) con Serverless Framework v3.

## Servicios

| Servicio | Path | Prefijo Lambda |
|---|---|---|
| `moc` | `services/moc` | `cdts-moc-*` |
| `digital_signature` | `services/digital_signature` | `cdts-digital-signature-*` |

Convención de nombres: `cdts-{service}-{function}`.

## Estructura

```
serverless-compose.yml
services/
  <service>/
    serverless.yml
    src/
      <function>/
        handler.py
        function.yml
```

## Requisitos

- Node.js 18+ y npm
- Serverless Framework v3:  `npm i -g serverless@3`
- Python 3.11 (runtime en Lambda)
- AWS CLI v2

## Instalación inicial

```bash
npm install
```

## Cargar credenciales AWS

Git Bash:
```bash
source ./scripts/load-aws-env.sh
```

PowerShell:
```powershell
. .\scripts\load-aws-env.ps1
```

## Deploy

Todo (compose):
```bash
npm run deploy
```

Un solo servicio:
```bash
cd services/digital_signature
serverless deploy
```

Solo una función:
```bash
cd services/digital_signature
serverless deploy function -f sign
```

## Remove

```bash
npm run remove                 # todo
cd services/moc && sls remove  # uno solo
```

## Logs en vivo

```bash
npm run logs:moc
npm run logs:sign
```

## Agregar una función nueva

1. Crear carpeta `services/<svc>/src/<nombre>/` con `handler.py` y `function.yml`.
2. Registrarla en `services/<svc>/serverless.yml` bajo `functions:`.
