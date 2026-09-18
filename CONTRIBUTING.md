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
4. Merge a `develop` dispara deploy a `dev`. Merge a `main` dispara deploy a `prod`.
5. Nombres de rama sugeridos:
   - `feat/<slug>` para features
   - `fix/<slug>` para bugs
   - `chore/<slug>` para tareas de infra / tooling
   - `docs/<slug>` para documentacion

## Flujo tipico

```bash
git checkout develop
git pull origin develop
git checkout -b feat/nombre-corto

# ...trabajo...
git add .
git commit -m "feat(scope): descripcion corta"
git push -u origin feat/nombre-corto

# abrir PR contra develop en la UI de GitHub
```

Cuando `develop` este listo para promover a produccion:

```bash
# desde la UI: abrir PR de develop -> main
```

## Convencion de commits

Usar [Conventional Commits](https://www.conventionalcommits.org/) en espanol o ingles:

- `feat(auth): agregar login por OTP`
- `fix(signature): corregir firma cuando OCR falla`
- `chore(ci): actualizar version de serverless`
- `docs(readme): documentar deploy manual`

## Tests

Todo cambio de logica debe traer su test. La suite corre en cada PR via GitHub Actions.

## Secrets

Nunca commitear credenciales AWS ni ninguna otra clave. Todo secret vive en GitHub Actions
Environments (`dev` / `prod`).
