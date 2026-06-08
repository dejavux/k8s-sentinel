#!/usr/bin/env bash
# Tekton BuildKit release for k8s-sentinel image.
#
# Usage:
#   ./release-sentinel-build.sh [image-tag]
#   REVISION=$(git rev-parse HEAD) ./release-sentinel-build.sh v0.1.0-dev
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
NS="${SENTINEL_TEKTON_NS:-ci-tenant-infra-bootstrap}"
REGISTRY="${SENTINEL_REGISTRY:-registry.docker-registry-internal.svc.cluster.local:5000}"
TAG="${1:-v0.1.0-dev}"
SENTINEL_SRC="${ROOT}/60_apps/k8s-sentinel"
REVISION="${REVISION:-$(git -C "$SENTINEL_SRC" rev-parse HEAD)}"
TIMEOUT="${SENTINEL_RELEASE_TIMEOUT:-1800s}"
# Faster feedback than shared fuqi default (120s)
export FUQI_K8S_WAIT_POLL_SEC="${SENTINEL_K8S_WAIT_POLL_SEC:-15}"

cd "$ROOT"

for secret in github-clone-credentials registry-push; do
  kubectl get secret "$secret" -n "$NS" >/dev/null 2>&1 || {
    echo "error: missing secret $secret in $NS" >&2
    echo "hint: kubectl get secret registry-push -n ci-tenant-fuqi-asset-manager -o yaml | sed 's/ci-tenant-fuqi-asset-manager/ci-tenant-infra-bootstrap/' | kubectl apply -f -" >&2
    exit 1
  }
done

# shellcheck disable=SC1091
source "$ROOT/scripts/lib/wait-k8s-workload.sh" 2>/dev/null || true
if declare -F check_internal_registry_ready >/dev/null 2>&1; then
  check_internal_registry_ready "$REGISTRY"
fi

parse_timeout_sec() {
  case "${1:-1800s}" in
    *h) echo $(( ${1%h} * 3600 )) ;;
    *m) echo $(( ${1%m} * 60 )) ;;
    *s) echo "${1%s}" ;;
    *) echo "${1}" ;;
  esac
}
TIMEOUT_SEC=$(parse_timeout_sec "$TIMEOUT")

echo "→ apply Tekton manifests"
kubectl apply -f "${SCRIPT_DIR}/pipeline-sentinel-release.yaml"

echo "→ PipelineRun k8s-sentinel-release revision=${REVISION} tag=${TAG}"
PR_NAME=$(
  kubectl create -f - -o jsonpath='{.metadata.name}' <<EOF
apiVersion: tekton.dev/v1
kind: PipelineRun
metadata:
  generateName: k8s-sentinel-release-
  namespace: ${NS}
  labels:
    app.kubernetes.io/part-of: k8s-sentinel
spec:
  pipelineRef:
    name: k8s-sentinel-release
  params:
    - name: revision
      value: ${REVISION}
    - name: registry
      value: ${REGISTRY}
    - name: image-tag
      value: ${TAG}
  workspaces:
    - name: source
      volumeClaimTemplate:
        spec:
          storageClassName: nfs-client
          accessModes:
            - ReadWriteMany
          resources:
            requests:
              storage: 32Gi
    - name: git-credentials
      secret:
        secretName: github-clone-credentials
        items:
          - key: token
            path: token
    - name: dockerconfig
      secret:
        secretName: registry-push
        items:
          - key: .dockerconfigjson
            path: config.json
  taskRunTemplate:
    serviceAccountName: tekton-ci-runner
    podTemplate:
      affinity:
        nodeAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            nodeSelectorTerms:
              - matchExpressions:
                  - key: nvidia.com/gpu
                    operator: NotIn
                    values: ["true"]
EOF
)

echo "   PipelineRun: ${PR_NAME}"
if declare -F wait_pipelinerun_failfast >/dev/null 2>&1; then
  wait_pipelinerun_failfast "$PR_NAME" "$NS" "$TIMEOUT_SEC" || exit 1
else
  kubectl wait --for=condition=Succeeded "pipelinerun/${PR_NAME}" -n "$NS" --timeout="${TIMEOUT}"
fi

echo "✅ pushed ${REGISTRY}/k8s-sentinel:${TAG}"
echo "   update deploy: make deploy APP=sentinel TAG=${TAG}"
