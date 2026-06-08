#!/usr/bin/env bash
# Build and push k8s-sentinel image to internal registry.
#
# Usage:
#   REGISTRY=registry-internal.3q.fi TAG=v0.1.0-dev ./build-push.sh
#   REGISTRY=registry.docker-registry-internal.svc.cluster.local:5000 TAG=v0.1.0-dev ./build-push.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REGISTRY="${REGISTRY:-registry-internal.3q.fi}"
TAG="${TAG:-v0.1.0-dev}"
IMAGE="${REGISTRY}/k8s-sentinel:${TAG}"

echo "→ docker build -t ${IMAGE}"
docker build -t "${IMAGE}" "${SCRIPT_DIR}"

echo "→ docker push ${IMAGE}"
docker push "${IMAGE}"

echo "✅ pushed ${IMAGE}"
echo "   deploy: SENTINEL_IMAGE=${IMAGE} SKIP_SENTINEL_SECRETS=1 bash deploy.sh"
