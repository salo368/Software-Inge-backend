# Contributing

> **Antes de crear un archivo o carpeta nueva, leer
> [`docs/repo-structure.md`](./docs/repo-structure.md).** Esa es la fuente unica de
> verdad sobre como se organiza el codigo (servicios, lambdas, layers, tests). La IA
> tambien la respeta via [`.cursor/rules/repo-structure.mdc`](./.cursor/rules/repo-structure.mdc).

## Reglas de oro

1. **Nada se mergea directo.** Todo cambio va por Pull Request.
2. `main` y `develop` estan protegidas. Ni siquiera los admins pueden hacer `git push` directo.
3. Las PR NO requieren review de pares (proyecto pequeno), pero SI requieren que todos los
   checks de CI queden en verde antes de mergear.
4. Merge a `develop` dispara deploy a `dev`. Merge a `main` dispara deploy a `pro`.
5. Nombres de rama:
   - `feat/<slug>` para features
   - `fix/<slug>` para bugs
   - `chore/<slug>` para tareas de infra / tooling
   - `docs/<slug>` para documentacion

## Flujo de branching

**Regla clave**: `develop` y `main` **nunca** se hablan entre si. No hay PRs de
`develop -> main` ni de `main -> develop`. Cada rama feature abre **dos PRs**: uno a
`develop` para validar en el ambiente `dev`, y luego el otro a `main` (desde la
**misma rama**) para desplegar a `pro`.

Motivo: los PRs se mergean con squash. Si en algun momento hicieramos `develop -> main`,
GitHub veria conflictos add/add en archivos porque cada squash crea un commit nuevo con
el mismo contenido. Mantener los dos sinks paralelos alimentados por la misma rama
elimina el problema.

### Diagrama

```
     main ── PR feat/x ── merge (squash) ──▶ deploy PRO
       │
       └── rama feat/x ── PR a develop ── merge (squash) ──▶ deploy DEV
```

Ambas ramas destino nacen de `main` conceptualmente (`develop` es un espejo
"probando" y `main` es "en produccion").

### Paso a paso

```bash
# 1) Partir SIEMPRE de main actualizado
git switch main
git pull origin main
git switch -c feat/mi-cambio

# 2) Trabajar
# ...editar, commits locales libres...
git push -u origin feat/mi-cambio

# 3) PR #1 a develop (para probar en dev)
gh pr create --base develop --head feat/mi-cambio \
    --title "feat(scope): mi cambio" --body "..."
#  esperar CI verde, merge con squash desde la UI
#  -> deploy-dev.yml dispara y actualiza el ambiente dev

# 4) Probar en dev. Si algo no sirve, corregir en la MISMA rama:
#    - hacer commits nuevos en feat/mi-cambio
#    - abrir PR a develop de nuevo (o reabrir con el mismo head, GH lo cierra al mergear)
#      Nota: como GH cierra la rama al mergear con --delete-branch, si necesitas
#      iterar mucho, evita --delete-branch en la primera vuelta o crea feat/mi-cambio-2.

# 5) PR #2 a main (para desplegar a pro), MISMA rama (o su continuacion)
gh pr create --base main --head feat/mi-cambio \
    --title "feat(scope): mi cambio" --body "..."
#  esperar CI verde, merge con squash desde la UI
#  -> deploy-pro.yml dispara y actualiza el ambiente pro
```

### Que NO hacer

- Abrir un PR de `develop` -> `main`.
- Abrir un PR de `main` -> `develop`.
- Crear una rama a partir de `develop`. Siempre partir de `main`.
- Reusar la misma rama para features distintos. Una rama = una unidad de cambio.

## Convencion de commits

Usar [Conventional Commits](https://www.conventionalcommits.org/) en espanol o ingles:

- `feat(auth): agregar login por OTP`
- `fix(signature): corregir firma cuando OCR falla`
- `chore(ci): actualizar version de serverless`
- `docs(readme): documentar deploy manual`

## Tests

Todo cambio de logica debe traer su test. Los tests viven en `backend/tests/`. La
suite corre en cada PR via GitHub Actions con `working-directory: backend`.

## Secrets

Nunca commitear credenciales AWS ni ninguna otra clave. Todo secret vive en GitHub Actions
Environments (`dev` / `pro`).
