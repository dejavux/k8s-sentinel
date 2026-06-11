# Helm 安裝

## 前置

- Kubernetes 1.24+
- `helm` 3.x
- Ansible host 修復（可選）：`k8s-sentinel-ansible-ssh` Secret + 節點 `authorized_keys`
- 1Password Operator（可選）：見 `manifests/overlays/onepassword/`

## Check-only（預設 — 建議首次試用）

```bash
helm upgrade --install k8s-sentinel ./charts/k8s-sentinel \
  -n kube-system \
  -f examples/helm/values-check-only.yaml
```

或從 ghcr release：

```bash
helm upgrade --install k8s-sentinel oci://ghcr.io/dejavux/charts/k8s-sentinel \
  --version 0.2.7 \
  -n kube-system
```

`config.autoFix=false`、`config.autoPR=false` — 僅掃描、不修改叢集。

## Ansible SSH 修復

適用 bare-metal / homelab：Pod 需能 SSH 到節點 IP。

```bash
kubectl create configmap k8s-sentinel-ansible-inventory \
  --from-file=hosts.yml=/path/to/hosts.yml \
  -n kube-system --dry-run=client -o yaml | kubectl apply -f -

kubectl create secret generic k8s-sentinel-ansible-ssh \
  --from-file=id_ed25519=/path/to/id_ed25519 \
  -n kube-system --dry-run=client -o yaml | kubectl apply -f -

helm upgrade --install k8s-sentinel ./charts/k8s-sentinel \
  -n kube-system \
  -f examples/helm/values-ansible.yaml \
  --set ansible.inventoryConfigMap=k8s-sentinel-ansible-inventory \
  --set ansible.remoteUser=YOUR_SSH_USER \
  --set config.autoFix=true
```

| Key | 說明 |
|-----|------|
| `ansible.enabled` | 掛 inventory + SSH Secret |
| `ansible.hostNetwork` | Pod 使用節點網路（常見於 bare-metal） |
| `ansible.remoteUser` | SSH 使用者（必填） |
| `config.diskAnsible` | disk 模組走 Ansible |

## 1Password Operator

```bash
helm upgrade --install k8s-sentinel ./charts/k8s-sentinel \
  -n kube-system \
  -f examples/helm/values-onepassword.yaml \
  --set onepassword.itemPath="vaults/MyVault/items/k8s-sentinel-credentials"
```

另需套用 `manifests/overlays/onepassword/onepassworditem.example.yaml`（改 vault/item 路徑）。

## GitOps（experimental）

需設定 `gitops.enabled=true` 與 `gitops.githubRepo`，並提供 `GITHUB_TOKEN` / `CURSOR_API_KEY` Secret。

環境變數 `SENTINEL_GITHUB_REPO` 為 Git clone 目標（無預設值）。

## 私有叢集 overlay

生產環境專用 values（內網 registry、inventory、vault 路徑）**不要** commit 到公開 repo。  
範例：infra-bootstrap `deploy/k8s-sentinel/values-3q-prod.yaml` — 見 [examples/private-cluster/README.md](../examples/private-cluster/README.md)。

## 常用 values

| Key | 說明 |
|-----|------|
| `config.modules` | 檢查模組 |
| `config.autoFix` | 自動修復 |
| `config.metricsFile` | Prometheus text 輸出路徑 |
| `onepassword.enabled` | 1Password Operator CR |
| `secrets.existingSecret` | 不用 1Password 時直接引用 Secret |
| `registry.endpoint` | containerd 修復用的 registry endpoint |

## 驗證

```bash
helm list -n kube-system -f k8s-sentinel
kubectl get cronjob k8s-sentinel -n kube-system
kubectl create job --from=cronjob/k8s-sentinel sentinel-check-$(date +%s) -n kube-system
kubectl logs -n kube-system -l job-name=sentinel-check-... -f
```

## 手動觸發（kubectl plugin）

```bash
kubectl sentinel trigger
kubectl sentinel logs --wait
kubectl sentinel check
```
