# Generic overlay — Kubernetes Secret (no 1Password Operator)

Helm is the recommended install path. This directory documents the **generic Secret** pattern
equivalent to `manifests/overlays/generic`.

## 1. Create Secret

```bash
kubectl create namespace kube-system --dry-run=client -o yaml | kubectl apply -f -

kubectl create secret generic k8s-sentinel-secrets -n kube-system \
  --from-literal=github-token='ghp_...' \
  --from-literal=cursor-api-key='...'   # optional, for GitOps
```

See [secret.example.yaml](./secret.example.yaml) for key names.

## 2. Helm install

```bash
helm upgrade --install k8s-sentinel ./charts/k8s-sentinel -n kube-system \
  -f examples/helm/values-check-only.yaml \
  --set secrets.existingSecret=k8s-sentinel-secrets
```

## 3. Enable GitOps (optional)

```bash
helm upgrade --install k8s-sentinel ./charts/k8s-sentinel -n kube-system \
  --set secrets.existingSecret=k8s-sentinel-secrets \
  --set gitops.enabled=true \
  --set gitops.githubRepo=your-org/your-infra-repo \
  --set config.autoPR=true
```

Never commit real tokens. Use Sealed Secrets, ESO, or 1Password overlay for production.
