# Proyecto Ingeniería de Software · Backend

> **Ejercicio académico** de la Pontificia Universidad Javeriana. No es un producto
> real ni está asociado a ninguna empresa; existe para practicar arquitectura
> serverless, CI/CD y buenas prácticas de repositorio.

Backend serverless multi-servicio en AWS (Lambda + API Gateway HTTP API) con
Serverless Framework v3. Todo el runtime vive bajo [`backend/`](./backend/); la raíz
agrupa solo infraestructura de proyecto (CI/CD, docs, reglas, IAM bootstrap).

La SPA que consume estas APIs vive en un repo aparte:
[`salo368/Software-Inge-frontend`](https://github.com/salo368/Software-Inge-frontend).
Se despliegan por separado y no comparten pipeline; el único punto de contacto es
AWS, donde el frontend publica su URL en un parámetro SSM para que el backend arme
enlaces absolutos hacia la SPA.

> **Estado:** rebuild post-MVP. La rama `develop` es la nueva base limpia. El codigo del MVP
> vive en la rama `legacy/mvp` como referencia y se migra por PRs pequenas.

**Antes de crear archivos, leer [`docs/repo-structure.md`](./docs/repo-structure.md).**

Docs adicionales del backend:

- [`docs/repo-structure.md`](./docs/repo-structure.md) — reglas de organización, deploy selectivo, naming.
- [`docs/signatures-v2.md`](./docs/signatures-v2.md) — servicio `signatures` (ciclo de vida, endpoints, mock CA, bootstrap SSM, integración con `processes`).
- [`docs/arquitectura_firma_digital_colombia_resumen.md`](./docs/arquitectura_firma_digital_colombia_resumen.md) — marco conceptual legal/criptográfico que motiva el diseño de `signatures`.
- [`backend/platform/migrations/README.md`](./backend/platform/migrations/README.md) — reglas duras de migraciones SQL.

## Layout del repo

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
- Las PR NO requieren aprobacion de pares, pero SI requieren que los checks de CI pasen
  **antes de poder mergear** (ver sección [CI/CD](#cicd) — el check de PR es liviano y
  no toca AWS; el deploy real solo corre después del merge).

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

Ver [`.github/workflows/`](./.github/workflows/). Hay dos momentos distintos en el
ciclo de vida de un cambio, con credenciales distintas:

- **En cada Pull Request** (hacia `develop` o hacia `main`): corre un check liviano
  y de solo lectura — lint + tests unitarios de los bloques afectados — **sin
  credenciales de AWS**. Es un *required status check*: el PR no se puede mergear
  si falla. No hace deploy ni toca infraestructura.
- **En cada push a `develop` o `main`** (es decir, apenas se mergea el PR):
  [`deploy-dev.yml`](./.github/workflows/deploy-dev.yml) o
  [`deploy-pro.yml`](./.github/workflows/deploy-pro.yml) corren la forma completa
  `plan → validate → deploy → summary`, con las credenciales del deployer de ese
  stage.

> **Motivo del cambio:** antes, un PR no disparaba ningún workflow — la única
> verificación ocurría *después* del merge, cuando el push a `develop`/`main` ya
> había arrancado el deploy. Eso contradecía la regla de arriba ("las PR SI
> requieren que los checks de CI pasen") y dejaba mergear cambios rotos sin
> aviso previo. El check de PR reutiliza los mismos pasos `validate`/`test` que
> ya existen en los workflows de deploy — no se duplica lógica ni se le da
> acceso a credenciales de AWS a un run disparado por PR.
>
> **Estado de implementación:** esta sección documenta la política ya acordada;
> el workflow que la implementa (agregar el disparador `pull_request` y marcarlo
> como *required status check* en `main`/`develop`) se agrega en un PR de
> seguimiento, sin más cambios al modelo de ramas descrito arriba.

### Deploy selectivo por bloque

El pipeline **no** re-despliega todo el backend en cada push. Agrupa el codigo
en **bloques** independientes (`backend/services/<X>/` y `backend/platform/<X>/`) y
solo despliega los afectados por el diff. Si tocas algo global del backend
(`serverless-compose.yml`, `config/`, `utils/`, `data/`, `layers/`, deps), se
redespliega **todo**. Detalles y reglas: [`docs/repo-structure.md`](./docs/repo-structure.md) §14.

## Infra bootstrap

La policy IAM y los usuarios que usa GitHub Actions estan documentados en
[`scripts/iam/README.md`](./scripts/iam/README.md).

<!-- pipeline test: only-outside-backend change; expected total_count=0. -->

