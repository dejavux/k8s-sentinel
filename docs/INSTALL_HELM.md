# Helm 安裝

## 前置

- Kubernetes 1.24+
- `helm` 3.x
- Ansible host 修復時：`k8s-sentinel-ansible-ssh` Secret + 節點 `authorized_keys`（見 infra-bootstrap `sync-cluster-ssh-keys.yml`）
- （可選）1Password Operator（3q overlay）

## Check-only（預設 values — 適合首次試用）

```bash
helm upgrade --install k8s-sentinel ./charts/k8s-sentinel \
  -n kube-system \
  --set image.repository=ghcr.io/dejavux/k8s-sentinel \
  --set image.tag=v0.2.3
```

`config.autoFix=false`、`config.autoPR=false` — 僅掃描、不修改叢集。

## 3q 叢集（infra-bootstrap）

**建議**：在 monorepo 根目錄：

```bash
make deploy APP=sentinel TAG=v0.2.3
# 或 build + deploy
make install APP=sentinel TAG=v0.2.4   # 含 resources 模組時
```

薄封裝：`deploy/k8s-sentinel/`（Helm overlay + `deploy.sh`）。

### Ansible / SSH 需求

disk、containerd 等 host 修復需從 Pod SSH 到 bare-metal IP：

| Chart values | 3q overlay |
|--------------|------------|
| `ansible.enabled` | `true` |
| `ansible.hostNetwork` | `true`（Pod 使用節點網路連 192.168.50.x） |
| `config.diskAnsible` | `true` |

infra-bootstrap `deploy.sh` 會：

- 掛 inventory ConfigMap + SSH Secret
- 執行 `40_k8s/playbooks/sync-cluster-ssh-keys.yml`（`access_policies.yml` SSOT + Sentinel 公鑰）

### 手動 Helm（無 deploy.sh）

```bash
kubectl create configmap k8s-sentinel-ansible-inventory \
  --from-file=hosts.yml=/path/to/hosts.yml \
  -n kube-system --dry-run=client -o yaml | kubectl apply -f -

helm upgrade --install k8s-sentinel ./charts/k8s-sentinel \
  -n kube-system \
  -f /path/to/values-3q-prod.yaml \
  --set image.repository=REGISTRY:5000/k8s-sentinel \
  --set image.tag=v0.2.3
```

## 常用 values

| Key | 說明 |
|-----|------|
| `config.modules` | 檢查模組（可加 `resources`；v0.2.4+） |
| `config.autoFix` | 自動修復 |
| `ansible.enabled` | inventory + SSH Secret 掛載 |
| `ansible.hostNetwork` | Pod 用 host 網路做 SSH |
| `onepassword.enabled` | 1Password Operator CR |
| `secrets.existingSecret` | 不用 1Password 時 |

## 驗證

```bash
helm list -n kube-system -f k8s-sentinel
kubectl get cronjob k8s-sentinel -n kube-system \
  -o jsonpath='modules={.spec.jobTemplate.spec.template.spec.containers[0].env[?(@.name=="SENTINEL_MODULES")].value}{"\n"}'
kubectl create job --from=cronjob/k8s-sentinel sentinel-check-$(date +%s) -n kube-system
```

`disk` 模組 log 應含各節點 `root_use_percent`（非 `ansible rc=4`）。
