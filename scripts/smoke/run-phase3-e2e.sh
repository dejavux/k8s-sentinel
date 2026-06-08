#!/usr/bin/env bash
# Phase 3 AnsibleRunner E2E (requires SSH to workers from this host).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
export SENTINEL_INFRA_ROOT="$ROOT"
export ANSIBLE_INVENTORY="${ANSIBLE_INVENTORY:-$ROOT/40_k8s/inventory/hosts.yml}"
export SENTINEL_PHASE3_E2E_LIMIT="${SENTINEL_PHASE3_E2E_LIMIT:-worker7}"
export SENTINEL_PHASE3_E2E_DRY_RUN="${SENTINEL_PHASE3_E2E_DRY_RUN:-true}"
cd "$ROOT/60_apps/k8s-sentinel/scripts"
exec python3 smoke/phase3_ansible_e2e.py
