# CDTS

Serverless multi-servicio en AWS (Lambda + API Gateway HTTP API) con Serverless Framework v4.

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

- Node.js 20+ y npm
- Serverless Framework v4:  `npm i -g serverless`
- Python 3.12
- AWS CLI v2

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
serverless deploy
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
serverless remove              # todo
cd services/moc && sls remove  # uno solo
```

## Agregar una función nueva

1. Crear carpeta `services/<svc>/src/<nombre>/` con `handler.py` y `function.yml`.
2. Registrarla en `services/<svc>/serverless.yml` bajo `functions:`.
