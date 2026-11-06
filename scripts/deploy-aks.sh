#!/usr/bin/env bash
# Build, push to ACR, and deploy CloudSaver API to AKS.
# Default overlay assumes the cluster can pull from ACR (e.g. az aks update --attach-acr).
# Use OVERLAY=aks-with-acr-pull-secret if you created docker-registry secret acr-pull.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

: "${ACR_NAME:?Set ACR_NAME (short name, no .azurecr.io)}"
: "${IMAGE_NAME:=cloudsaver-api}"
: "${IMAGE_TAG:=v1}"
REGISTRY="${ACR_NAME}.azurecr.io"
FULL_IMAGE="${FULL_IMAGE:-${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}}"
export DOCKER_DEFAULT_PLATFORM="${DOCKER_DEFAULT_PLATFORM:-linux/amd64}"

if ! command -v az >/dev/null 2>&1; then
  echo "Azure CLI (az) is required." >&2
  exit 1
fi

echo "Logging in to ACR ${ACR_NAME} ..."
az acr login --name "$ACR_NAME"

echo "Building ${FULL_IMAGE} ..."
docker build -f "${ROOT}/Dockerfile" -t "$FULL_IMAGE" "$ROOT"

echo "Pushing ${FULL_IMAGE} ..."
docker push "$FULL_IMAGE"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

K8S_TMP="${TMP}/k8s"
mkdir -p "${K8S_TMP}/overlays/deploy"
cp -a "${ROOT}/k8s/base" "${K8S_TMP}/"

OVERLAY="${OVERLAY:-aks}"
case "${OVERLAY}" in
  aks)
    SRC="${ROOT}/k8s/overlays/aks"
    ;;
  aks-with-acr-pull-secret)
    SRC="${ROOT}/k8s/overlays/aks-with-acr-pull-secret"
    ;;
  aks-loadbalancer)
    SRC="${ROOT}/k8s/overlays/aks-loadbalancer"
    ;;
  aks-loadbalancer-with-acr-pull-secret)
    SRC="${ROOT}/k8s/overlays/aks-loadbalancer-with-acr-pull-secret"
    ;;
  *)
    echo "OVERLAY must be aks, aks-with-acr-pull-secret, aks-loadbalancer, or aks-loadbalancer-with-acr-pull-secret" >&2
    exit 1
    ;;
esac
cp -a "${SRC}/." "${K8S_TMP}/overlays/deploy/"

cat >"${K8S_TMP}/overlays/deploy/kustomization.yaml" <<EOF
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../../base
images:
  - name: cloudsaver-api
    newName: ${REGISTRY}/${IMAGE_NAME}
    newTag: ${IMAGE_TAG}
EOF

case "${OVERLAY}" in
  aks-with-acr-pull-secret)
    cat >>"${K8S_TMP}/overlays/deploy/kustomization.yaml" <<'EOF'
patches:
  - path: deployment-patch.yaml
EOF
    ;;
  aks-loadbalancer)
    cat >>"${K8S_TMP}/overlays/deploy/kustomization.yaml" <<'EOF'
patches:
  - path: service-patch.yaml
EOF
    ;;
  aks-loadbalancer-with-acr-pull-secret)
    cat >>"${K8S_TMP}/overlays/deploy/kustomization.yaml" <<'EOF'
patches:
  - path: deployment-patch.yaml
  - path: service-patch.yaml
EOF
    ;;
esac

echo "Applying Kustomize overlay (${OVERLAY}) ..."
kubectl apply -k "${K8S_TMP}/overlays/deploy"

kubectl -n cloudsaver rollout status deployment/cloudsaver-api --timeout=300s

echo "Done."
if [[ "${OVERLAY}" == "aks-loadbalancer" ]] || [[ "${OVERLAY}" == "aks-loadbalancer-with-acr-pull-secret" ]]; then
  echo "External IP: kubectl -n cloudsaver get svc cloudsaver-api"
else
  echo "Port-forward: kubectl -n cloudsaver port-forward svc/cloudsaver-api 8080:80"
fi
