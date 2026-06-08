#!/usr/bin/env bash
# K8s Sentinel — Helm deploy (replaces legacy kubectl apply manifests/rbac+cronjob).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHART_DIR="${SCRIPT_DIR}/charts/k8s-sentinel"
NAMESPACE="${SENTINEL_NAMESPACE:-kube-system}"
RELEASE_NAME="${SENTINEL_RELEASE_NAME:-k8s-sentinel}"
INFRA_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
INVENTORY_SRC="${SENTINEL_INVENTORY_SRC:-${INFRA_ROOT}/40_k8s/inventory/hosts.yml}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $*"; }
warn() { echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] WARN:${NC} $*"; }
error() { echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ERROR:${NC} $*"; exit 1; }

check_prerequisites() {
  log "檢查前置需求..."
  command -v kubectl >/dev/null 2>&1 || error "kubectl not found"
  command -v helm >/dev/null 2>&1 || error "helm not found"
  kubectl cluster-info >/dev/null 2>&1 || error "Cannot connect to Kubernetes cluster"
  [[ -d "${CHART_DIR}" ]] || error "Helm chart not found: ${CHART_DIR}"
  log "✓ Prerequisites check passed"
}

resolve_registry_image() {
  local tag="${SENTINEL_TAG:-v0.1.0-dev}"
  if [[ -n "${SENTINEL_IMAGE:-}" ]]; then
    echo "${SENTINEL_IMAGE%:*} ${SENTINEL_IMAGE##*:}"
    return 0
  fi
  local reg
  reg="$(kubectl get svc registry -n docker-registry-internal -o jsonpath='{.spec.clusterIP}' 2>/dev/null || true)"
  [[ -n "${reg}" ]] || error "registry ClusterIP not found (namespace docker-registry-internal)"
  echo "${reg}:5000/k8s-sentinel ${tag}"
}

resolve_registry_endpoint() {
  if [[ -n "${SENTINEL_REGISTRY:-}" ]]; then
    echo "${SENTINEL_REGISTRY}"
    return 0
  fi
  local reg
  reg="$(kubectl get svc registry -n docker-registry-internal -o jsonpath='{.spec.clusterIP}' 2>/dev/null || true)"
  [[ -n "${reg}" ]] || error "registry ClusterIP not found (namespace docker-registry-internal)"
  echo "${reg}:5000"
}

deploy_ansible_inventory() {
  if [[ ! -f "${INVENTORY_SRC}" ]]; then
    warn "Ansible inventory not found: ${INVENTORY_SRC} — skip ConfigMap"
    return 0
  fi
  log "部署 Ansible inventory ConfigMap..."
  kubectl create configmap k8s-sentinel-ansible-inventory \
    --from-file=hosts.yml="${INVENTORY_SRC}" \
    -n "${NAMESPACE}" \
    --dry-run=client -o yaml | kubectl apply -f -
  log "✓ Ansible inventory ConfigMap deployed"
}

ensure_ansible_ssh_secret() {
  if kubectl get secret k8s-sentinel-ansible-ssh -n "${NAMESPACE}" &>/dev/null; then
    log "✓ Ansible SSH secret exists"
    return 0
  fi
  local key=""
  if [[ -f "${HOME}/.ssh/id_ed25519" ]]; then
    key="${HOME}/.ssh/id_ed25519"
  elif [[ -f "${HOME}/.ssh/id_rsa" ]]; then
    key="${HOME}/.ssh/id_rsa"
  fi
  if [[ -z "${key}" ]]; then
    warn "No ~/.ssh/id_ed25519 or id_rsa — create k8s-sentinel-ansible-ssh manually for host fixes"
    return 0
  fi
  log "Creating k8s-sentinel-ansible-ssh from ${key}..."
  kubectl create secret generic k8s-sentinel-ansible-ssh \
    -n "${NAMESPACE}" \
    --from-file="$(basename "${key}")=${key}" \
    --dry-run=client -o yaml | kubectl apply -f -
  log "✓ Ansible SSH secret created"
}

remove_legacy_manifests() {
  if kubectl get cronjob k8s-sentinel -n "${NAMESPACE}" \
    -o jsonpath='{.metadata.annotations.meta\.helm\.sh/release-name}' 2>/dev/null | grep -q .; then
    return 0
  fi
  if kubectl get cronjob k8s-sentinel -n "${NAMESPACE}" &>/dev/null; then
    warn "Removing legacy CronJob (replaced by Helm release ${RELEASE_NAME})..."
    kubectl delete cronjob k8s-sentinel -n "${NAMESPACE}" --ignore-not-found
  fi
}

helm_deploy() {
  local repo tag endpoint
  read -r repo tag <<< "$(resolve_registry_image)"
  endpoint="$(resolve_registry_endpoint)"

  local -a helm_args=(
    upgrade --install "${RELEASE_NAME}" "${CHART_DIR}"
    -n "${NAMESPACE}"
    --create-namespace
    -f "${CHART_DIR}/values-3q-prod.yaml"
    --set "image.repository=${repo}"
    --set "image.tag=${tag}"
    --set "registry.endpoint=${endpoint}"
  )

  if [[ "${SKIP_SENTINEL_SECRETS:-0}" == "1" ]]; then
    helm_args+=(--set onepassword.enabled=false)
    warn "SKIP_SENTINEL_SECRETS=1 — onepassword.enabled=false（沿用既有 Secret）"
  fi

  log "Helm deploy ${RELEASE_NAME} (image=${repo}:${tag})..."
  helm "${helm_args[@]}"
  log "✓ Helm release ${RELEASE_NAME} deployed"
}

verify_deployment() {
  log "驗證部署..."
  kubectl get sa,clusterrole,clusterrolebinding,cronjob -n "${NAMESPACE}" \
    -l "app.kubernetes.io/instance=${RELEASE_NAME}" 2>/dev/null || true
  kubectl get cronjob "${RELEASE_NAME}" -n "${NAMESPACE}" >/dev/null 2>&1 \
    || error "CronJob ${RELEASE_NAME} not found"
  log "✓ Deployment verification passed"
}

show_usage() {
  log "部署完成！"
  cat <<EOF

下一步：
  kubectl get cronjob ${RELEASE_NAME} -n ${NAMESPACE}
  kubectl create job --from=cronjob/${RELEASE_NAME} sentinel-check-\$(date +%s) -n ${NAMESPACE}
  helm get values ${RELEASE_NAME} -n ${NAMESPACE}

Repo: https://github.com/dejavux/k8s-sentinel (private)
Chart: ${CHART_DIR}

EOF
}

main() {
  log "開始部署 K8s Sentinel（Helm）..."
  check_prerequisites
  deploy_ansible_inventory
  ensure_ansible_ssh_secret
  remove_legacy_manifests
  helm_deploy
  verify_deployment
  show_usage
  log "✓ K8s Sentinel 部署完成！"
}

main "$@"
