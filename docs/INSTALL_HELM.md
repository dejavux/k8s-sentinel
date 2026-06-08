# Helm 安裝

## 前置

- Kubernetes 1.24+
- `helm` 3.x
- （可選）1Password Operator、`k8s-sentinel-ansible-ssh` Secret

## Check-only（預設 values — 適合首次試用）

```bash
helm upgrade --install k8s-sentinel ./charts/k8s-sentinel \
  -n kube-system \
  --set image.repository=ghcr.io/dejavux/k8s-sentinel \
  --set image.tag=v0.2.0
```

`config.autoFix=false`、`config.autoPR=false` — 僅掃描、不修改叢集。

## 3q 叢集（完整修復 + GitOps + Ansible）

```bash
# 先建立 inventory ConfigMap + SSH secret（與 deploy.sh 相同）
kubectl create configmap k8s-sentinel-ansible-inventory \
  --from-file=hosts.yml=../../40_k8s/inventory/hosts.yml \
  -n kube-system --dry-run=client -o yaml | kubectl apply -f -

helm upgrade --install k8s-sentinel ./charts/k8s-sentinel \
  -n kube-system \
  -f ./charts/k8s-sentinel/values-3q-prod.yaml
```

## 常用 values

| Key | 說明 |
|-----|------|
| `config.modules` | 檢查模組（逗號分隔） |
| `config.autoFix` | 自動修復 |
| `ansible.enabled` | 掛 inventory + SSH |
| `ansible.inventoryContent` | 內嵌 `hosts.yml`（chart 建 ConfigMap） |
| `secrets.create` + `secrets.githubToken` | 不用 1Password 時 |
| `onepassword.enabled` | 1Password Operator CR |

## 驗證

```bash
helm template k8s-sentinel ./charts/k8s-sentinel -f ./charts/k8s-sentinel/values-3q-prod.yaml | kubeconform -summary -
kubectl get cronjob -n kube-system -l app.kubernetes.io/name=k8s-sentinel
```
