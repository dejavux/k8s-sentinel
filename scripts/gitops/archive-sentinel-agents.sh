#!/usr/bin/env bash
# Bulk archive k8s-sentinel Cursor cloud agents (sidebar cleanup).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

if [[ -f "${ROOT}/../../../.env" ]]; then
  # infra-bootstrap root when run from submodule
  set -a
  # shellcheck disable=SC1091
  source "${ROOT}/../../../.env" 2>/dev/null || true
  set +a
fi
if [[ -f "${ROOT}/../../.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${ROOT}/../../.env" 2>/dev/null || true
  set +a
fi

exec npx --prefix "$ROOT" tsx "$ROOT/scripts/gitops/archive_sentinel_agents.ts" "$@"
