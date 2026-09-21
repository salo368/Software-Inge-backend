#!/usr/bin/env bash
# Computes what the pipeline should do based on the git diff.
#
# Mental model (see docs/repo-structure.md §14, §15):
#
#   * services  = business domains under backend/services/<X>/. Each one
#                 has its own package: validate -> test -> deploy ->
#                 integration. Multiple services deploy in parallel.
#
#   * infra     = cross-cutting infrastructure under backend/platform/
#                 (currently `migrations` and `assets`). NOT services --
#                 they don't own handlers with test.py / integration.py.
#                 They are deploy-only steps. If any of them runs, it is
#                 because SOMETHING transversal changed, which by rule
#                 forces a redeploy of every service (transversal = shared
#                 code, config or infra that any service could depend on).
#
# Decision tree per changed file:
#   - backend/services/<X>/**                  -> mark service X as changed
#   - backend/platform/migrations/**           -> run migrations + transversal
#   - backend/platform/assets/**               -> run assets     + transversal
#   - anything else inside backend/            -> transversal
#   - outside backend/                         -> ignored
#
# Cardinal rule: ANY infra execution forces a full redeploy of every
# service. Migrations change the DB schema and assets change references
# baked into templates/emails; deploying only a subset would leave the
# fleet split between old and new expectations. So both content changes
# (new SQL file, new asset) AND code changes to the infra block set
# transversal=true. The distinction between infra-content / infra-code is
# kept only for the log line so operators see what kind of change caused
# the fan-out.
#
# When transversal is true, services_to_deploy expands to ALL services.
#
# Outputs on $GITHUB_OUTPUT:
#   services_to_deploy   JSON array of service names to (re)deploy
#   services_count       length of services_to_deploy
#   run_migrations       "true"|"false"
#   run_assets           "true"|"false"
#   run_infrastructure   "true" if run_migrations OR run_assets
#   transversal          "true" if any non-service change forced full fan-out
#   total_count          services_count + (1 per infra step that runs)
#                        Zero means the workflow has nothing to do.
#
# Legacy outputs `blocks` and `count` are still emitted for one release so
# any external tooling checking them keeps working; they mirror the old
# behaviour (union of services + infra, migrations first).

set -euo pipefail

log() { echo "$@" >&2; }

# Per-infra-block, list of subdirs that are content-only (do NOT force
# transversal). Anything under a platform block that is NOT in this list
# is treated as code/config for the infra block and forces transversal.
declare -A INFRA_CONTENT_DIRS=(
  ["migrations"]="sql"
  ["assets"]="files"
)

CHANGED_FILES=""

# Testing hook: PLAN_DEPLOY_TEST_CHANGED_FILES can inject a newline-separated
# file list to skip real diff detection. Used by unit tests only.
if [[ -n "${PLAN_DEPLOY_TEST_CHANGED_FILES:-}" ]]; then
  CHANGED_FILES="${PLAN_DEPLOY_TEST_CHANGED_FILES}"
  log "== TEST MODE: using injected CHANGED_FILES"
elif [[ -n "${MANUAL_BLOCK:-}" ]]; then
  log "== manual: MANUAL_BLOCK='${MANUAL_BLOCK}'"
elif [[ "${GITHUB_EVENT_NAME:-}" == "pull_request" ]]; then
  BASE_REF="${GITHUB_BASE_REF:-main}"
  log "== PR: diff vs origin/${BASE_REF}"
  git fetch --no-tags --depth=200 origin "${BASE_REF}" >/dev/null 2>&1 || true
  MERGE_BASE="$(git merge-base "origin/${BASE_REF}" HEAD 2>/dev/null || echo "")"
  if [[ -n "${MERGE_BASE}" ]]; then
    CHANGED_FILES="$(git diff --name-only "${MERGE_BASE}" HEAD)"
  else
    log "::warning::no merge-base with origin/${BASE_REF}, assuming full deploy"
    CHANGED_FILES="__FORCE_ALL__"
  fi
elif [[ "${GITHUB_EVENT_NAME:-}" == "push" ]]; then
  BEFORE="${GITHUB_EVENT_BEFORE:-}"
  if [[ -z "${BEFORE}" || "${BEFORE}" == "0000000000000000000000000000000000000000" ]]; then
    log "::warning::push without valid BEFORE (new branch or force-push), assuming full deploy"
    CHANGED_FILES="__FORCE_ALL__"
  elif ! git cat-file -e "${BEFORE}^{commit}" 2>/dev/null; then
    log "::warning::BEFORE ${BEFORE} not present locally, assuming full deploy"
    CHANGED_FILES="__FORCE_ALL__"
  else
    log "== push: diff ${BEFORE}..HEAD"
    CHANGED_FILES="$(git diff --name-only "${BEFORE}" HEAD)"
  fi
else
  log "== local: diff HEAD^..HEAD"
  CHANGED_FILES="$(git diff --name-only HEAD^ HEAD 2>/dev/null || echo "")"
fi

# ---------------------------------------------------------------------------
# Discover services and infra blocks from the tree.
# ---------------------------------------------------------------------------
ALL_SERVICES=()
if [[ -d backend/services ]]; then
  while IFS= read -r -d '' d; do
    ALL_SERVICES+=("$(basename "${d}")")
  done < <(find backend/services -mindepth 1 -maxdepth 1 -type d -print0 2>/dev/null | sort -z)
fi

ALL_INFRA=()
if [[ -d backend/platform ]]; then
  while IFS= read -r -d '' d; do
    ALL_INFRA+=("$(basename "${d}")")
  done < <(find backend/platform -mindepth 1 -maxdepth 1 -type d -print0 2>/dev/null | sort -z)
fi

log "== services discovered: ${ALL_SERVICES[*]:-<none>}"
log "== infra discovered:    ${ALL_INFRA[*]:-<none>}"

# ---------------------------------------------------------------------------
# Classify one changed file. Emits one of:
#   service:<name>            file lives under backend/services/<name>/
#   infra-content:<name>      file is content-only for infra <name>
#   infra-code:<name>         file is code/config for infra <name>
#                             (forces transversal)
#   backend-global            file is inside backend/ but not tied to any
#                             block (forces transversal)
#   outside                   file is outside backend/ (ignored)
# ---------------------------------------------------------------------------
classify_change() {
  local f="$1"

  if [[ "${f}" =~ ^backend/services/([^/]+)/ ]]; then
    echo "service:${BASH_REMATCH[1]}"; return
  fi

  if [[ "${f}" =~ ^backend/platform/([^/]+)/(.*)$ ]]; then
    local iblock="${BASH_REMATCH[1]}"
    local sub="${BASH_REMATCH[2]}"
    local content_dirs="${INFRA_CONTENT_DIRS[$iblock]:-}"
    if [[ -n "${content_dirs}" ]]; then
      IFS=',' read -ra dirs <<< "${content_dirs}"
      for cd in "${dirs[@]}"; do
        if [[ "${sub}" == "${cd}/"* || "${sub}" == "${cd}" ]]; then
          echo "infra-content:${iblock}"; return
        fi
      done
    fi
    echo "infra-code:${iblock}"; return
  fi

  if [[ "${f}" =~ ^backend/ ]]; then
    echo "backend-global"; return
  fi

  echo "outside"
}

# ---------------------------------------------------------------------------
# Aggregate the classifications into the four outputs.
# ---------------------------------------------------------------------------
services_hit=()
run_migrations="false"
run_assets="false"
transversal="false"

apply_infra_content() {
  # Content-only touch to an infra block (new SQL file, new asset) runs
  # that infra step AND forces transversal per the cardinal rule.
  case "$1" in
    migrations) run_migrations="true" ;;
    assets)     run_assets="true" ;;
    *)          log "::warning::unknown infra '$1', ignoring content-only hit"; return ;;
  esac
  transversal="true"
}

apply_infra_code() {
  # Code/config touch to an infra block. Same effect as content: runs the
  # infra step AND forces transversal. Kept as a separate function so the
  # log line above distinguishes the two.
  case "$1" in
    migrations) run_migrations="true" ;;
    assets)     run_assets="true" ;;
    *)          log "::warning::unknown infra '$1'"; return ;;
  esac
  transversal="true"
}

if [[ -n "${MANUAL_BLOCK:-}" ]]; then
  # Manual override from workflow_dispatch. Interpretation:
  #   __all__            -> everything (all services + every infra step, transversal)
  #   <service-name>     -> only that service
  #   <infra-name>       -> only that infra step (no service redeploy)
  if [[ "${MANUAL_BLOCK}" == "__all__" ]]; then
    services_hit=("${ALL_SERVICES[@]}")
    for i in "${ALL_INFRA[@]:-}"; do apply_infra_code "${i}"; done
  elif [[ " ${ALL_SERVICES[*]} " =~ " ${MANUAL_BLOCK} " ]]; then
    services_hit=("${MANUAL_BLOCK}")
  elif [[ " ${ALL_INFRA[*]} " =~ " ${MANUAL_BLOCK} " ]]; then
    apply_infra_content "${MANUAL_BLOCK}"
  else
    log "::error::MANUAL_BLOCK='${MANUAL_BLOCK}' is neither a service (${ALL_SERVICES[*]}) nor an infra (${ALL_INFRA[*]}) nor '__all__'"
    exit 1
  fi
elif [[ "${CHANGED_FILES}" == "__FORCE_ALL__" ]]; then
  services_hit=("${ALL_SERVICES[@]}")
  for i in "${ALL_INFRA[@]:-}"; do apply_infra_code "${i}"; done
elif [[ -z "${CHANGED_FILES}" ]]; then
  log "== no changes, nothing to deploy"
else
  log "== changed files:"
  echo "${CHANGED_FILES}" | sed 's/^/   /' >&2

  while IFS= read -r f; do
    [[ -z "${f}" ]] && continue
    kind="$(classify_change "${f}")"
    case "${kind}" in
      service:*)         services_hit+=("${kind#service:}") ;;
      infra-content:*)   apply_infra_content "${kind#infra-content:}" ;;
      infra-code:*)      apply_infra_code   "${kind#infra-code:}"   ;;
      backend-global)    transversal="true" ;;
      outside)           : ;;
    esac
  done <<<"${CHANGED_FILES}"
fi

# Cardinal rule enforcement. Applies to auto-detect AND to manual overrides
# that touched infra (e.g. `MANUAL_BLOCK=migrations`), so a manual infra
# run cannot leave the fleet mid-deploy.
if [[ "${transversal}" == "true" ]]; then
  log "== transversal change detected -> forcing redeploy of ALL services"
  services_hit=("${ALL_SERVICES[@]}")
fi

# Dedupe + sort services alphabetically. Deploy order across services does
# not matter (each has its own CloudFormation stack, run in parallel).
services=()
if [[ ${#services_hit[@]} -gt 0 ]]; then
  while IFS= read -r s; do
    [[ -n "${s}" ]] && services+=("${s}")
  done < <(printf '%s\n' "${services_hit[@]}" | sort -u)
fi

# ---------------------------------------------------------------------------
# Serialize outputs.
# ---------------------------------------------------------------------------
services_json="[]"
if [[ ${#services[@]} -gt 0 ]]; then
  services_json="["
  for i in "${!services[@]}"; do
    [[ $i -gt 0 ]] && services_json+=","
    services_json+="\"${services[$i]}\""
  done
  services_json+="]"
fi

run_infrastructure="false"
[[ "${run_migrations}" == "true" || "${run_assets}" == "true" ]] && run_infrastructure="true"

# infra_steps: ordered list of infra blocks to run inside the infrastructure
# job (migrations first, then assets). Used by the caller for its logging
# and by the infrastructure job's own summary.
infra_ordered=()
[[ "${run_migrations}" == "true" ]] && infra_ordered+=("migrations")
[[ "${run_assets}" == "true"     ]] && infra_ordered+=("assets")

infra_json="[]"
if [[ ${#infra_ordered[@]} -gt 0 ]]; then
  infra_json="["
  for i in "${!infra_ordered[@]}"; do
    [[ $i -gt 0 ]] && infra_json+=","
    infra_json+="\"${infra_ordered[$i]}\""
  done
  infra_json+="]"
fi

total_count=$(( ${#services[@]} + ${#infra_ordered[@]} ))

# Legacy outputs (blocks / count / blocks_others / others_count / has_migrations)
# kept so downstream tooling doesn't break during the transition. Prefer the
# new outputs above.
legacy_ordered=()
[[ "${run_migrations}" == "true" ]] && legacy_ordered+=("migrations")
[[ "${run_assets}"     == "true" ]] && legacy_ordered+=("assets")
for s in "${services[@]:-}"; do legacy_ordered+=("${s}"); done

legacy_json="[]"
if [[ ${#legacy_ordered[@]} -gt 0 ]]; then
  legacy_json="["
  for i in "${!legacy_ordered[@]}"; do
    [[ $i -gt 0 ]] && legacy_json+=","
    legacy_json+="\"${legacy_ordered[$i]}\""
  done
  legacy_json+="]"
fi

log "== plan:"
log "     services_to_deploy = ${services_json}"
log "     run_migrations     = ${run_migrations}"
log "     run_assets         = ${run_assets}"
log "     transversal        = ${transversal}"
log "     total_count        = ${total_count}"

if [[ "${DRY_RUN:-0}" == "1" ]]; then
  log "== DRY_RUN active, skipping GITHUB_OUTPUT"
  exit 0
fi

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  {
    echo "services_to_deploy=${services_json}"
    echo "services_count=${#services[@]}"
    echo "infra_steps=${infra_json}"
    echo "run_migrations=${run_migrations}"
    echo "run_assets=${run_assets}"
    echo "run_infrastructure=${run_infrastructure}"
    echo "transversal=${transversal}"
    echo "total_count=${total_count}"
    # Legacy / compatibility outputs.
    echo "blocks=${legacy_json}"
    echo "count=${total_count}"
  } >>"${GITHUB_OUTPUT}"
fi
