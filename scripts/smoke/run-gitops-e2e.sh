#!/usr/bin/env bash
# GitOps E2E: fallback PR meta + optional Cursor SDK + optional cluster gh smoke.
#
# Usage:
#   ./scripts/smoke/run-gitops-e2e.sh
#   ./scripts/smoke/run-gitops-e2e.sh --with-cursor
#   ./scripts/smoke/run-gitops-e2e.sh --cluster-smoke
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}/scripts"

PY_ARGS=()
CLUSTER_SMOKE=0
for arg in "$@"; do
  case "${arg}" in
    --with-cursor) PY_ARGS+=(--with-cursor) ;;
    --cluster-smoke) CLUSTER_SMOKE=1 ;;
  esac
done

echo "→ GitOps fault-injection (fallback meta)"
python3 smoke/gitops_e2e.py "${PY_ARGS[@]}"

if [[ "${CLUSTER_SMOKE}" == "1" ]]; then
  echo "→ Cluster Phase 4 gh smoke (draft PR create/close)"
  kubectl apply -f "${ROOT}/manifests/job-phase4-smoke.yaml"
  kubectl wait -n kube-system --for=condition=complete job/k8s-sentinel-phase4-smoke --timeout=300s
  kubectl logs -n kube-system -l phase=phase4-smoke --tail=50
  kubectl delete job k8s-sentinel-phase4-smoke -n kube-system --ignore-not-found
  echo "✓ cluster gh smoke OK"
fi

echo "✓ gitops e2e done"
