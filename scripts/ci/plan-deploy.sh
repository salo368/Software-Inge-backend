#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# plan-deploy.sh
#
# Decide que "bloques" de backend hay que desplegar en funcion de los archivos
# que cambiaron. Se usa en GitHub Actions (deploy-dev.yml, deploy-pro.yml,
# ci.yml en modo dry-run).
#
# Bloques posibles:
#   - Cada servicio en backend/services/<name>/ (detecta automaticamente los
#     directorios).
#   - "migrations" (backend/migrations/): carpeta de SQL versionados que se
#     ejecutan en orden.
#
# Reglas:
#   1. Si cambia SOLO dentro de un bloque -> se despliega ese bloque.
#   2. Si cambia algo "global" del backend (compose, config, utils, data,
#      layers, package.json, requirements, .nvmrc, .python-version) -> se
#      redespliegan TODOS los bloques.
#   3. Si cambia solo doc/CI project-wide y nada dentro de backend/ -> no se
#      despliega nada.
#
# Orden:
#   - "migrations" siempre primero.
#   - El resto en orden alfabetico.
#
# Modos:
#   - Modo real (default): imprime el plan y lo escribe en $GITHUB_OUTPUT como
#     variable "blocks" (JSON array).
#   - Modo dry-run (env DRY_RUN=1): solo imprime, no escribe output.
#
# Override manual:
#   - Env MANUAL_BLOCK con un nombre de bloque valido: fuerza el deploy de ese
#     bloque unico.
#   - Env MANUAL_BLOCK="__all__": fuerza deploy total.
# ------------------------------------------------------------------------------

set -euo pipefail

log() { echo "$@" >&2; }

# ---- 1. Determinar el rango de cambios --------------------------------------

CHANGED_FILES=""

if [[ -n "${MANUAL_BLOCK:-}" ]]; then
  log "== Modo manual: MANUAL_BLOCK='${MANUAL_BLOCK}'"
elif [[ "${GITHUB_EVENT_NAME:-}" == "pull_request" ]]; then
  BASE_REF="${GITHUB_BASE_REF:-main}"
  log "== PR: diff contra origin/${BASE_REF}"
  git fetch --no-tags --depth=200 origin "${BASE_REF}" >/dev/null 2>&1 || true
  MERGE_BASE="$(git merge-base "origin/${BASE_REF}" HEAD 2>/dev/null || echo "")"
  if [[ -n "${MERGE_BASE}" ]]; then
    CHANGED_FILES="$(git diff --name-only "${MERGE_BASE}" HEAD)"
  else
    log "::warning::No hay merge-base con origin/${BASE_REF}; asumo deploy total."
    CHANGED_FILES="__FORCE_ALL__"
  fi
elif [[ "${GITHUB_EVENT_NAME:-}" == "push" ]]; then
  BEFORE="${GITHUB_EVENT_BEFORE:-}"
  if [[ -z "${BEFORE}" || "${BEFORE}" == "0000000000000000000000000000000000000000" ]]; then
    log "::warning::Push sin BEFORE valido (rama nueva o force-push); asumo deploy total."
    CHANGED_FILES="__FORCE_ALL__"
  elif ! git cat-file -e "${BEFORE}^{commit}" 2>/dev/null; then
    log "::warning::Commit BEFORE ${BEFORE} no existe localmente; asumo deploy total."
    CHANGED_FILES="__FORCE_ALL__"
  else
    log "== Push: diff ${BEFORE}..HEAD"
    CHANGED_FILES="$(git diff --name-only "${BEFORE}" HEAD)"
  fi
else
  log "== Modo local: diff HEAD^..HEAD"
  CHANGED_FILES="$(git diff --name-only HEAD^ HEAD 2>/dev/null || echo "")"
fi

# ---- 2. Descubrir todos los bloques posibles --------------------------------

ALL_BLOCKS=()

# Servicios
if [[ -d backend/services ]]; then
  while IFS= read -r -d '' svc_dir; do
    svc_name="$(basename "${svc_dir}")"
    ALL_BLOCKS+=("${svc_name}")
  done < <(find backend/services -mindepth 1 -maxdepth 1 -type d -print0 2>/dev/null | sort -z)
fi

# migrations
if [[ -d backend/migrations ]]; then
  ALL_BLOCKS+=("migrations")
fi

log "== Bloques descubiertos: ${ALL_BLOCKS[*]:-<ninguno>}"

# ---- 3. Decidir bloques a desplegar -----------------------------------------

selected=()

order_blocks() {
  # Recibe una lista de bloques por stdin y los reordena: migrations primero,
  # despues alfabetico. Deduplica.
  local sorted
  sorted="$(sort -u)"
  local out=()
  if echo "${sorted}" | grep -qx 'migrations'; then
    out+=("migrations")
  fi
  while IFS= read -r b; do
    [[ -z "${b}" || "${b}" == "migrations" ]] && continue
    out+=("${b}")
  done <<<"${sorted}"
  printf '%s\n' "${out[@]}"
}

if [[ -n "${MANUAL_BLOCK:-}" ]]; then
  # Override manual
  if [[ "${MANUAL_BLOCK}" == "__all__" ]]; then
    selected=("${ALL_BLOCKS[@]}")
  else
    # Validar que el bloque existe
    if [[ ! " ${ALL_BLOCKS[*]} " =~ " ${MANUAL_BLOCK} " ]]; then
      log "::error::MANUAL_BLOCK='${MANUAL_BLOCK}' no coincide con ningun bloque descubierto (${ALL_BLOCKS[*]:-<ninguno>})."
      exit 1
    fi
    selected=("${MANUAL_BLOCK}")
  fi
elif [[ "${CHANGED_FILES}" == "__FORCE_ALL__" ]]; then
  selected=("${ALL_BLOCKS[@]}")
elif [[ -z "${CHANGED_FILES}" ]]; then
  log "== No hay cambios. Nada que desplegar."
  selected=()
else
  log "== Archivos cambiados:"
  echo "${CHANGED_FILES}" | sed 's/^/   /' >&2

  # Global backend -> deploy total
  GLOBAL_REGEX='^backend/(serverless-compose\.yml|package\.json|package-lock\.json|requirements-dev\.txt|requirements\.txt|\.nvmrc|\.python-version|pytest\.ini|config/|utils/|data/|layers/)'
  if echo "${CHANGED_FILES}" | grep -qE "${GLOBAL_REGEX}"; then
    log "== Cambio global en backend/. Deploy TODOS los bloques."
    selected=("${ALL_BLOCKS[@]}")
  else
    # Bloques especificos
    tmp=()
    # Servicios afectados
    while IFS= read -r svc; do
      [[ -z "${svc}" ]] && continue
      tmp+=("${svc}")
    done < <(echo "${CHANGED_FILES}" | grep -oE '^backend/services/[^/]+' | awk -F/ '{print $3}' | sort -u)
    # migrations
    if echo "${CHANGED_FILES}" | grep -qE '^backend/migrations/'; then
      tmp+=("migrations")
    fi
    if [[ ${#tmp[@]} -gt 0 ]]; then
      # Filtrar solo bloques realmente existentes en ALL_BLOCKS
      for b in "${tmp[@]}"; do
        if [[ " ${ALL_BLOCKS[*]} " =~ " ${b} " ]]; then
          selected+=("${b}")
        else
          log "::warning::Bloque '${b}' referenciado en el diff pero no existe en el arbol; ignorando."
        fi
      done
    fi
  fi
fi

# ---- 4. Ordenar y emitir ----------------------------------------------------

ordered=()
if [[ ${#selected[@]} -gt 0 ]]; then
  while IFS= read -r b; do
    ordered+=("${b}")
  done < <(printf '%s\n' "${selected[@]}" | order_blocks)
fi

log "== Plan final (${#ordered[@]} bloque(s)):"
if [[ ${#ordered[@]} -eq 0 ]]; then
  log "   <ninguno>"
  json="[]"
else
  for b in "${ordered[@]}"; do
    log "   - ${b}"
  done
  # JSON array sin depender de jq
  json="["
  for i in "${!ordered[@]}"; do
    [[ $i -gt 0 ]] && json+=","
    json+="\"${ordered[$i]}\""
  done
  json+="]"
fi

log "== blocks=${json}"

if [[ "${DRY_RUN:-0}" == "1" ]]; then
  log "== DRY_RUN activo, no se escribe GITHUB_OUTPUT."
  exit 0
fi

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  {
    echo "blocks=${json}"
    echo "count=${#ordered[@]}"
  } >>"${GITHUB_OUTPUT}"
fi
