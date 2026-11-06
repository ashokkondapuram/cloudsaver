# CloudSaver — minimal Kubernetes (Docker Desktop & AKS)

This layout deploys the **CloudSaver API** from the repository root [`Dockerfile`](../Dockerfile) (uvicorn on port **8000**). It is intended for smoke tests and demos, not a full production stack (no Postgres/Redis/workers here).

**Namespace:** `cloudsaver`.

## Docker Desktop Kubernetes

```bash
chmod +x scripts/deploy-docker-desktop.sh
./scripts/deploy-docker-desktop.sh
```

Port-forward and check health:

```bash
kubectl -n cloudsaver port-forward svc/cloudsaver-api 8080:80
curl -s http://127.0.0.1:8080/healthz
```

The Deployment sets minimal `CLOUDSAVER_*` env vars so the API can start with a **demo workspace** (see `k8s/base/deployment.yaml`). Replace with ConfigMaps/Secrets for real use.

## Azure Kubernetes Service (AKS)

Prerequisites: `az`, `kubectl`, Docker; cluster credentials (`az aks get-credentials …`).

**Attach ACR** (recommended — no pull secret):

```bash
az aks update -n <AKS_NAME> -g <RG> --attach-acr $(az acr show -n "$ACR_NAME" --query id -o tsv)
```

Deploy:

```bash
chmod +x scripts/deploy-aks.sh
export ACR_NAME=<short-acr-name>
./scripts/deploy-aks.sh
```

Optional `OVERLAY` values: `aks` (default), `aks-with-acr-pull-secret`, `aks-loadbalancer`, `aks-loadbalancer-with-acr-pull-secret`.

For a pull secret named `acr-pull` in namespace `cloudsaver`:

```bash
kubectl create secret docker-registry acr-pull \
  --namespace cloudsaver \
  --docker-server="${ACR_NAME}.azurecr.io" \
  --docker-username=<id> \
  --docker-password=<password> \
  --dry-run=client -o yaml | kubectl apply -f -
OVERLAY=aks-with-acr-pull-secret ./scripts/deploy-aks.sh
```

## Manual apply (without scripts)

Edit `k8s/overlays/aks/kustomization.yaml` `images` block, then:

```bash
kubectl apply -k k8s/overlays/aks/
```

## Uninstall

```bash
kubectl delete -k k8s/overlays/docker-desktop/
kubectl delete namespace cloudsaver
```
