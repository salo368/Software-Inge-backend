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
│   ├── config/, utils/, data/   ← cross-bloque dentro del backend
│   ├── services/                ← bloques de DOMINIO DE NEGOCIO (<name>/)
│   ├── platform/                ← bloques de INFRAESTRUCTURA (<name>/, ej. migrations)
│   ├── layers/shared/           ← Lambda Layer con codigo compartido
│   └── tests/
├── README.md
├── CONTRIBUTING.md
└── .gitignore
```

Detalle completo de la estructura backend: [`docs/repo-structure.md`](./docs/repo-structure.md).

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

- [`ci.yml`](./.github/workflows/ci.yml) - corre en cada PR (build+test + preview del plan de deploy)
- [`deploy-dev.yml`](./.github/workflows/deploy-dev.yml) - deploy a `dev` en push a `develop`
- [`deploy-pro.yml`](./.github/workflows/deploy-pro.yml) - deploy a `pro` en push a `main`

Los tres workflows corren con `working-directory: backend`.

### Deploy selectivo por bloque

El pipeline **no** re-despliega todo el backend en cada push. Agrupa el codigo
en **bloques** independientes (`backend/services/<X>/` y `backend/migrations/`) y
solo despliega los afectados por el diff. Si tocas algo global del backend
(`serverless-compose.yml`, `config/`, `utils/`, `data/`, `layers/`, deps), se
redespliega **todo**. Detalles y reglas: [`docs/repo-structure.md`](./docs/repo-structure.md) §14.

## Infra bootstrap

La policy IAM y los usuarios que usa GitHub Actions estan documentados en
[`scripts/iam/README.md`](./scripts/iam/README.md).
