# CDTS

Proyecto serverless multi-servicio en AWS (Lambda + API Gateway HTTP API + S3/CloudFront)
con Serverless Framework v3.

> **Estado:** rebuild post-MVP. La rama `develop` es la nueva base limpia. El codigo del MVP
> vive en la rama `legacy/mvp` como referencia y se migra por PRs pequenas.

**Antes de crear archivos, leer [`docs/repo-structure.md`](./docs/repo-structure.md).**

## Flujo de trabajo

- **Todo cambio va por Pull Request**. No se permite `git push` directo a `main` ni a `develop`.
- Ramas de trabajo se crean **siempre desde `main`**: `feat/<nombre>`, `fix/<nombre>`,
  `chore/<nombre>`, `docs/<nombre>`.
- Cada rama abre **dos PRs**: uno a `develop` (para desplegar y probar en `dev`) y
  uno a `main` (para desplegar en `pro`). **La misma rama** alimenta ambos ambientes.
- `develop` y `main` **nunca** se mergean entre si (evita conflictos add/add del squash).
- Las PR NO requieren aprobacion de pares, pero SI requieren que los checks de CI pasen.

Detalle completo con comandos y anti-patrones: [`CONTRIBUTING.md`](./CONTRIBUTING.md).

## Ambientes

Solo dos stages: `dev` y `pro`. No usar `prod`, `staging`, `qa`, etc.

| Stage | Rama disparadora | GitHub Environment | Usuario IAM |
|---|---|---|---|
| `dev` | `develop` | `dev` | `github-actions-dev-deployer` |
| `pro` | `main`    | `pro` | `github-actions-pro-deployer` |

Region unica: `us-east-1`. Ambos stages viven en la misma cuenta AWS (`658548982073`).

## Naming de recursos AWS

Toda Lambda se nombra `cdts-<stage>-<service>-<function>`. Ver
[`docs/repo-structure.md`](./docs/repo-structure.md) §3.

## Estructura esperada

```
serverless-compose.yml
config/          ← configuracion declarativa cross-project
utils/           ← utilidades genericas cross-domain (fuente de layers/shared)
data/            ← datos estaticos cross-project
services/
  <service>/
    serverless.yml
    utils/       ← helpers privados del dominio
    data/        ← modelos, DTOs, schemas del dominio
    src/
      handlers/    ← API Lambdas
      scheduled/   ← Cron Lambdas
      workers/     ← Async / queue Lambdas
layers/
  shared/
tests/
scripts/
  iam/
```

Detalle completo: [`docs/repo-structure.md`](./docs/repo-structure.md).

## Requisitos locales

- Node.js 20 LTS (ver `.nvmrc`)
- Python 3.11 (ver `.python-version`)
- Serverless Framework v3 -> se instala con `npm install`
- AWS CLI v2 (solo para dev local)

## Setup local

```bash
npm install
python -m venv .venv
source .venv/Scripts/activate    # Windows Git Bash
# o: source .venv/bin/activate   # Linux/Mac
pip install -r requirements-dev.txt
```

## Deploy manual (solo emergencias)

El deploy oficial pasa por GitHub Actions. Si necesitas correr uno local, exporta las
credenciales del deployer correspondiente:

```bash
npm run deploy:dev
# o
npm run deploy:pro
```

## Tests

```bash
npm test
```

## CI/CD

Ver [`.github/workflows/`](./.github/workflows/):

- [`ci.yml`](./.github/workflows/ci.yml) - corre en cada PR (lint + tests + `serverless print`)
- [`deploy-dev.yml`](./.github/workflows/deploy-dev.yml) - deploy a `dev` en push a `develop`
- [`deploy-pro.yml`](./.github/workflows/deploy-pro.yml) - deploy a `pro` en push a `main`

## Infra bootstrap

La policy IAM y los usuarios que usa GitHub Actions estan documentados en
[`scripts/iam/README.md`](./scripts/iam/README.md).
