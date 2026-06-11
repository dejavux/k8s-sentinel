#!/usr/bin/env bash
# Build and push k8s-sentinel image.
#
# Usage:
#   TAG=v0.2.7 ./build-push.sh
#   REGISTRY=ghcr.io/dejavux TAG=v0.2.7 ./build-push.sh
#   REGISTRY=registry-internal.example.com TAG=v0.2.7 ./build-push.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REGISTRY="${REGISTRY:-ghcr.io/dejavux}"
TAG="${TAG:-latest}"
IMAGE="${REGISTRY}/k8s-sentinel:${TAG}"

echo "→ docker build -t ${IMAGE}"
docker build -t "${IMAGE}" "${SCRIPT_DIR}"

echo "→ docker push ${IMAGE}"
docker push "${IMAGE}"

echo "✅ pushed ${IMAGE}"
echo "   deploy: SENTINEL_IMAGE=${IMAGE} SKIP_SENTINEL_SECRETS=1 bash deploy.sh"
