#!/usr/bin/env bash
# Build the repo Dockerfile locally and deploy to Docker Desktop Kubernetes (imagePullPolicy: Never).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_NAME="${IMAGE_NAME:-cloudsaver-api}"
IMAGE_TAG="${IMAGE_TAG:-local}"
export DOCKER_DEFAULT_PLATFORM="${DOCKER_DEFAULT_PLATFORM:-linux/amd64}"

echo "Building ${IMAGE_NAME}:${IMAGE_TAG} from repo root Dockerfile ..."
docker build -f "${ROOT}/Dockerfile" -t "${IMAGE_NAME}:${IMAGE_TAG}" "$ROOT"

echo "Applying Kustomize overlay docker-desktop ..."
kubectl apply -k "${ROOT}/k8s/overlays/docker-desktop"

echo "Waiting for rollout ..."
kubectl -n cloudsaver rollout status deployment/cloudsaver-api --timeout=300s

echo "Done. Port-forward: kubectl -n cloudsaver port-forward svc/cloudsaver-api 8080:80"
echo "Health: curl -s http://127.0.0.1:8080/healthz"
