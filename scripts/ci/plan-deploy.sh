#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# plan-deploy.sh
#
# Decide que "bloques" de backend hay que desplegar en funcion de los archivos
# que cambiaron. Se usa en GitHub Actions (deploy-dev.yml, deploy-pro.yml,
# ci.yml en modo dry-run).
#
# Estructura de bloques:
#   - backend/services/<name>/  -> bloque de DOMINIO DE NEGOCIO
#   - backend/platform/<name>/  -> bloque de INFRAESTRUCTURA runtime
#     (ej: platform/migrations aplica el esquema SQL)
#
# Reglas:
#   1. Si el diff toca SOLO archivos dentro de uno o mas bloques conocidos ->
#      se despliegan solo esos bloques.
#   2. Si el diff toca CUALQUIER archivo dentro de backend/ que no pertenezca a
#      un bloque (compose, config, utils, data, layers, deps, o cualquier
#      archivo suelto) -> se re-despliegan TODOS los bloques. Esto es
#      conservador a proposito: mejor un deploy total innecesario que un
#      servicio quedando desincronizado silenciosamente.
#   3. Si el diff SOLO toca archivos fuera de backend/ -> no se despliega nada.
#
# Orden de deploy:
#   - "migrations" siempre primero (aplica esquema antes que arranquen los
#     servicios que dependen).
#   - El resto en orden alfabetico.
#
# Modos:
#   - Modo real (default): imprime el plan y lo escribe en $GITHUB_OUTPUT como
#     "blocks" (JSON array) y "count".
#   - Modo dry-run (env DRY_RUN=1): solo imprime, no escribe output.
#
# Override manual (env MANUAL_BLOCK):
#   - "<nombre>": fuerza deploy de ese unico bloque (debe existir en el arbol).
#   - "__all__":  fuerza deploy total.
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

# services/ = dominios de negocio
if [[ -d backend/services ]]; then
  while IFS= read -r -d '' d; do
    ALL_BLOCKS+=("$(basename "${d}")")
  done < <(find backend/services -mindepth 1 -maxdepth 1 -type d -print0 2>/dev/null | sort -z)
fi

# platform/ = infraestructura runtime
if [[ -d backend/platform ]]; then
  while IFS= read -r -d '' d; do
    ALL_BLOCKS+=("$(basename "${d}")")
  done < <(find backend/platform -mindepth 1 -maxdepth 1 -type d -print0 2>/dev/null | sort -z)
fi

log "== Bloques descubiertos: ${ALL_BLOCKS[*]:-<ninguno>}"

# ---- 3. Decidir bloques a desplegar -----------------------------------------

selected=()

order_blocks() {
  # Recibe una lista por stdin y la reordena: migrations primero, resto
  # alfabetico. Deduplica.
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

classify_change() {
  # Recibe un path relativo y responde por stdout una linea con:
  #   "block:<nombre>"    si pertenece a un bloque conocido
  #   "outside-backend"   si esta fuera de backend/
  #   "backend-global"    si esta en backend/ pero no en un bloque
  local f="$1"
  if [[ "${f}" =~ ^backend/services/([^/]+)/ ]]; then
    echo "block:${BASH_REMATCH[1]}"
  elif [[ "${f}" =~ ^backend/platform/([^/]+)/ ]]; then
    echo "block:${BASH_REMATCH[1]}"
  elif [[ "${f}" =~ ^backend/ ]]; then
    echo "backend-global"
  else
    echo "outside-backend"
  fi
}

if [[ -n "${MANUAL_BLOCK:-}" ]]; then
  # Override manual
  if [[ "${MANUAL_BLOCK}" == "__all__" ]]; then
    selected=("${ALL_BLOCKS[@]}")
  else
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

  # Clasificar cada archivo
  has_backend_global=0
  block_hits=()
  while IFS= read -r f; do
    [[ -z "${f}" ]] && continue
    kind="$(classify_change "${f}")"
    case "${kind}" in
      backend-global)
        has_backend_global=1
        ;;
      block:*)
        block_hits+=("${kind#block:}")
        ;;
      outside-backend)
        : # ignorar
        ;;
    esac
  done <<<"${CHANGED_FILES}"

  if [[ ${has_backend_global} -eq 1 ]]; then
    log "== Cambio en archivo backend/ fuera de cualquier bloque -> deploy TOTAL."
    selected=("${ALL_BLOCKS[@]}")
  elif [[ ${#block_hits[@]} -gt 0 ]]; then
    for b in "${block_hits[@]}"; do
      if [[ " ${ALL_BLOCKS[*]} " =~ " ${b} " ]]; then
        selected+=("${b}")
      else
        log "::warning::Bloque '${b}' referenciado en el diff pero no existe en el arbol; ignorando."
      fi
    done
  else
    log "== Cambios solo fuera de backend/. Nada que desplegar."
    selected=()
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
