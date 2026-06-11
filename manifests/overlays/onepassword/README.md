# 1Password Operator overlay

Use when [1Password Connect Operator](https://developer.1password.com/docs/k8s/operator/) is installed.

## Helm (recommended)

```bash
helm upgrade --install k8s-sentinel ./charts/k8s-sentinel -n kube-system \
  -f examples/helm/values-onepassword.yaml \
  --set onepassword.itemPath='vaults/YourVault/items/k8s-sentinel-credentials'
```

The chart renders a `OnePasswordItem` CR when `onepassword.enabled=true`.
Secret name: `k8s-sentinel-secrets` (keys: `github-token`, `cursor-api-key`).

## Raw manifest reference

See [onepassworditem.example.yaml](./onepassworditem.example.yaml).

## 1Password for Open Source

Eligible OSS projects may apply for a free Teams account:
https://github.com/1Password/for-open-source
