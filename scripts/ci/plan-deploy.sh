#!/usr/bin/env bash
# Computes which blocks to deploy based on the git diff.
# Blocks: backend/services/<X>/ and backend/platform/<X>/.
# See docs/repo-structure.md.

set -euo pipefail

log() { echo "$@" >&2; }

# Per platform block, list of subdirs treated as "content-only".
# Changes ONLY inside these subdirs deploy just the block; anything else in the
# platform block is treated as backend-global (deploys the entire backend).
declare -A PLATFORM_CONTENT_DIRS=(
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

# Discover blocks
ALL_BLOCKS=()
if [[ -d backend/services ]]; then
  while IFS= read -r -d '' d; do
    ALL_BLOCKS+=("$(basename "${d}")")
  done < <(find backend/services -mindepth 1 -maxdepth 1 -type d -print0 2>/dev/null | sort -z)
fi
if [[ -d backend/platform ]]; then
  while IFS= read -r -d '' d; do
    ALL_BLOCKS+=("$(basename "${d}")")
  done < <(find backend/platform -mindepth 1 -maxdepth 1 -type d -print0 2>/dev/null | sort -z)
fi

log "== discovered blocks: ${ALL_BLOCKS[*]:-<none>}"

# Order: migrations first so the schema is ready, then the rest alphabetically.
order_blocks() {
  local sorted
  sorted="$(sort -u)"
  local out=()
  if echo "${sorted}" | grep -qx 'migrations'; then out+=("migrations"); fi
  while IFS= read -r b; do
    [[ -z "${b}" || "${b}" == "migrations" ]] && continue
    out+=("${b}")
  done <<<"${sorted}"
  printf '%s\n' "${out[@]}"
}

classify_change() {
  local f="$1"
  if [[ "${f}" =~ ^backend/services/([^/]+)/ ]]; then
    echo "block:${BASH_REMATCH[1]}"; return
  fi
  if [[ "${f}" =~ ^backend/platform/([^/]+)/(.*)$ ]]; then
    local block="${BASH_REMATCH[1]}"
    local sub="${BASH_REMATCH[2]}"
    local content_dirs="${PLATFORM_CONTENT_DIRS[$block]:-}"
    if [[ -n "${content_dirs}" ]]; then
      IFS=',' read -ra dirs <<< "${content_dirs}"
      for cd in "${dirs[@]}"; do
        if [[ "${sub}" == "${cd}/"* || "${sub}" == "${cd}" ]]; then
          echo "block:${block}"; return
        fi
      done
    fi
    # Code/config change inside a platform block -> full backend redeploy.
    echo "backend-global"; return
  fi
  if [[ "${f}" =~ ^backend/ ]]; then
    echo "backend-global"; return
  fi
  echo "outside"
}

selected=()

if [[ -n "${MANUAL_BLOCK:-}" ]]; then
  if [[ "${MANUAL_BLOCK}" == "__all__" ]]; then
    selected=("${ALL_BLOCKS[@]}")
  else
    if [[ ! " ${ALL_BLOCKS[*]} " =~ " ${MANUAL_BLOCK} " ]]; then
      log "::error::MANUAL_BLOCK='${MANUAL_BLOCK}' not found in ${ALL_BLOCKS[*]:-<none>}"
      exit 1
    fi
    selected=("${MANUAL_BLOCK}")
  fi
elif [[ "${CHANGED_FILES}" == "__FORCE_ALL__" ]]; then
  selected=("${ALL_BLOCKS[@]}")
elif [[ -z "${CHANGED_FILES}" ]]; then
  log "== no changes, nothing to deploy"
else
  log "== changed files:"
  echo "${CHANGED_FILES}" | sed 's/^/   /' >&2

  has_backend_global=0
  block_hits=()
  while IFS= read -r f; do
    [[ -z "${f}" ]] && continue
    kind="$(classify_change "${f}")"
    case "${kind}" in
      backend-global)   has_backend_global=1 ;;
      block:*)          block_hits+=("${kind#block:}") ;;
      outside)          : ;;
    esac
  done <<<"${CHANGED_FILES}"

  if [[ ${has_backend_global} -eq 1 ]]; then
    log "== backend global change -> full backend deploy"
    selected=("${ALL_BLOCKS[@]}")
  elif [[ ${#block_hits[@]} -gt 0 ]]; then
    for b in "${block_hits[@]}"; do
      if [[ " ${ALL_BLOCKS[*]} " =~ " ${b} " ]]; then
        selected+=("${b}")
      else
        log "::warning::block '${b}' in diff but not in tree, ignoring"
      fi
    done
  fi

  if [[ ${#selected[@]} -eq 0 ]]; then
    log "== only non-deployable changes, nothing to deploy"
  fi
fi

ordered=()
if [[ ${#selected[@]} -gt 0 ]]; then
  while IFS= read -r b; do
    ordered+=("${b}")
  done < <(printf '%s\n' "${selected[@]}" | order_blocks)
fi

log "== plan (${#ordered[@]} block(s)):"
if [[ ${#ordered[@]} -eq 0 ]]; then
  log "   <none>"
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
  log "== DRY_RUN active, skipping GITHUB_OUTPUT"
  exit 0
fi

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  {
    echo "blocks=${json}"
    echo "count=${#ordered[@]}"
  } >>"${GITHUB_OUTPUT}"
fi
