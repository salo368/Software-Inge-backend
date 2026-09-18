# CDTS

Proyecto serverless multi-servicio en AWS (Lambda + API Gateway HTTP API + S3/CloudFront)
con Serverless Framework v3.

> **Estado:** rebuild post-MVP. La rama `develop` es la nueva base limpia. El codigo del MVP
> vive en la historia de `main` como referencia y se migra por PRs pequenas.

## Flujo de trabajo

- **Todo cambio va por Pull Request**. No se permite `git push` directo a `main` ni a `develop`.
- Ramas de trabajo: `feat/<nombre>`, `fix/<nombre>`, `chore/<nombre>` -> PR a `develop`.
- Merge a `develop` -> deploy automatico al stage `dev` en AWS via GitHub Actions.
- PR de `develop` -> `main` -> merge -> deploy automatico al stage `prod`.
- Las PR NO requieren aprobacion de pares, pero SI requieren que los checks de CI pasen.

## Ambientes

| Stage | Rama disparadora | GitHub Environment | Usuario IAM |
|---|---|---|---|
| `dev`  | `develop` | `dev`  | `github-actions-dev-deployer`  |
| `prod` | `main`    | `prod` | `github-actions-prod-deployer` |

Region unica: `us-east-1`. Ambos stages viven en la misma cuenta AWS (`658548982073`).

## Estructura esperada

```
serverless-compose.yml
services/
  <service>/
    serverless.yml
    src/
      <function>/
        handler.py
        function.yml
layers/
  shared/
    ...
frontend/
frontend-firma/
tests/
scripts/
  iam/
    github-actions-deploy-policy.json
```

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
npm run deploy:prod
```

## Tests

```bash
npm test
```

## CI/CD

Ver [`.github/workflows/`](./.github/workflows/):

- [`ci.yml`](./.github/workflows/ci.yml) - corre en cada PR (lint + tests + `serverless print`)
- [`deploy-dev.yml`](./.github/workflows/deploy-dev.yml) - deploy a `dev` en push a `develop`
- [`deploy-prod.yml`](./.github/workflows/deploy-prod.yml) - deploy a `prod` en push a `main`

## Infra bootstrap

La policy IAM y los usuarios que usa GitHub Actions estan documentados en
[`scripts/iam/README.md`](./scripts/iam/README.md).
