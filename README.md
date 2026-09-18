# CDTS

Proyecto serverless multi-servicio en AWS (Lambda + API Gateway HTTP API + S3/CloudFront)
con Serverless Framework v3. La aplicación completa vive bajo [`backend/`](./backend/);
la raíz del repo agrupa solo infraestructura de proyecto (CI/CD, docs, reglas, IAM
bootstrap).

> **Estado:** rebuild post-MVP. La rama `develop` es la nueva base limpia. El codigo del MVP
> vive en la rama `legacy/mvp` como referencia y se migra por PRs pequenas.

**Antes de crear archivos, leer [`docs/repo-structure.md`](./docs/repo-structure.md).**

## Layout del monorepo

```
repo/
├── .github/workflows/           ← CI/CD (project-wide)
├── .cursor/rules/               ← reglas persistentes para la IA
├── docs/                        ← documentacion humana
├── scripts/iam/                 ← infra IAM bootstrap (project-wide)
├── backend/                     ← ★ todo el runtime del backend
│   ├── serverless-compose.yml
│   ├── package.json
│   ├── requirements-dev.txt
│   ├── pytest.ini
│   ├── .nvmrc, .python-version
│   ├── config/, utils/, data/   ← cross-servicio dentro del backend
│   ├── services/                ← <domain>/serverless.yml + src/{handlers,scheduled,workers}
│   ├── layers/shared/           ← Lambda Layer con codigo compartido
│   └── tests/
├── README.md
├── CONTRIBUTING.md
└── .gitignore
```

Detalle completo de la estructura backend: [`docs/repo-structure.md`](./docs/repo-structure.md).

## Flujo de trabajo

- **Todo cambio va por Pull Request**. No se permite `git push` directo a `main` ni a `develop`.
- Ramas de trabajo: `feat/<nombre>`, `fix/<nombre>`, `chore/<nombre>`, `docs/<nombre>` -> PR a `develop`.
- Merge a `develop` -> deploy automatico al stage `dev` en AWS via GitHub Actions.
- PR de `develop` -> `main` -> merge -> deploy automatico al stage `pro`.
- Las PR NO requieren aprobacion de pares, pero SI requieren que los checks de CI pasen.

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

## Requisitos locales

- Node.js 20 LTS (ver `backend/.nvmrc`)
- Python 3.11 (ver `backend/.python-version`)
- Serverless Framework v3 -> se instala con `npm install` dentro de `backend/`
- AWS CLI v2 (solo para dev local)

## Setup local

```bash
cd backend
npm install
python -m venv .venv
source .venv/Scripts/activate    # Windows Git Bash
# o: source .venv/bin/activate   # Linux/Mac
pip install -r requirements-dev.txt
```

## Deploy manual (solo emergencias)

El deploy oficial pasa por GitHub Actions. Si necesitas correr uno local, exporta las
credenciales del deployer correspondiente y ejecuta desde `backend/`:

```bash
cd backend
npm run deploy:dev
# o
npm run deploy:pro
```

## Tests

```bash
cd backend
npm test
```

## CI/CD

Ver [`.github/workflows/`](./.github/workflows/):

- [`ci.yml`](./.github/workflows/ci.yml) - corre en cada PR (lint + tests + `serverless print`)
- [`deploy-dev.yml`](./.github/workflows/deploy-dev.yml) - deploy a `dev` en push a `develop`
- [`deploy-pro.yml`](./.github/workflows/deploy-pro.yml) - deploy a `pro` en push a `main`

Los tres workflows corren con `working-directory: backend`.

## Infra bootstrap

La policy IAM y los usuarios que usa GitHub Actions estan documentados en
[`scripts/iam/README.md`](./scripts/iam/README.md).
