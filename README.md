# K8s Sentinel - 自動化叢集健康檢查與修復

**狀態**: 🟢 MVP 運作中（含 containerd/kubelet；公開 repo 規劃見 [docs/PUBLIC_REPO_PLAN.md](docs/PUBLIC_REPO_PLAN.md)）
**版本**: v0.1.0-dev
**維護者**: Infrastructure Team

---

## 🎯 概述

K8s Sentinel 是一個自動化的 Kubernetes 叢集健康檢查與修復系統，能夠：

- 🔍 **定期掃描**：CronJob 每 30 分鐘檢查叢集健康
- 🔧 **自動修復**：整合 Ansible + Cursor SDK 處理常見問題
- 📝 **GitOps 整合**：修復後自動提交 PR 並 merge
- 🎮 **手動觸發**：支援 kubectl plugin 手動執行特定模組

---

## 📋 功能模組

| 模組 | 檢查項目 | 自動修復 | 狀態 |
|------|---------|---------|------|
| `runc` | runc 可用性 | ✅ Ansible | ✅ |
| `disk` | DiskPressure / host rootfs（Ansible df） | ✅ CI Pod 清理 + Ansible（host） | ✅ |
| `containerd` | CRI / runtime Unknown、NodeStatusUnknown | ✅ Ansible `fix-containerd-cri` + uncordon | ✅ |
| `kubelet` | NotReady、kubelet restart、uncordon | ✅ systemctl + uncordon | ✅ |
| `pods` | Pod 異常狀態 | ✅ 叢集內 + GitOps PR | ✅ |
| `components` | 平台組件（kube-proxy、CoreDNS…） | ✅ Pod 重啟 | ✅ |
| `resources` | 資源使用率 | ❌ 僅告警 | 📋 待實作 |

---

## 🚀 快速開始

### 前置需求

- Kubernetes 1.24+
- kubectl 已配置
- 1Password Connect + Operator（用於 secrets 管理）
- （可選）Cursor API Key（用於 AI 生成修復方案）

### 映像拉取（kubelet）

節點 **無法** 直接拉 `registry-internal.3q.fi`（需 chart `kubeletHttps`）或 `*.svc.cluster.local`（節點 DNS 限制）。

**建議**（與 Tekton `make install APP=sentinel` 一致）：

1. `make configure-sentinel-registry-mirror`（Ansible：containerd HTTP mirror → registry ClusterIP:5000）
2. 或暫用 `manifests/daemonset-preload-image.yaml` 預載後 CronJob `imagePullPolicy: IfNotPresent`
3. CronJob 映像格式：`$(kubectl get svc registry -n docker-registry-internal -o jsonpath='{.spec.clusterIP}'):5000/k8s-sentinel:v0.1.0-dev`

### 安裝

**Helm（推薦）** — 見 [docs/INSTALL_HELM.md](docs/INSTALL_HELM.md)

```bash
helm upgrade --install k8s-sentinel ./charts/k8s-sentinel -n kube-system
# 3q 叢集：-f ./charts/k8s-sentinel/values-3q-prod.yaml
```

**infra-bootstrap（3q 叢集）**

```bash
# build + Helm deploy（含 registry mirror）
make install APP=sentinel

# 僅部署（沿用既有映像）
make deploy APP=sentinel TAG=v0.1.0-dev
```

`deploy.sh` 為 Helm wrapper（`values-3q-prod.yaml`）。舊版 `manifests/rbac.yaml` / `cronjob.yaml` 已廢棄，見 [manifests/DEPRECATED.md](manifests/DEPRECATED.md)。

### 手動觸發

```bash
# 檢查所有模組
kubectl create job --from=cronjob/k8s-sentinel \
  sentinel-check-$(date +%s) -n kube-system

# 檢查特定模組
kubectl create job --from=cronjob/k8s-sentinel \
  sentinel-check-runc-$(date +%s) -n kube-system \
  -- check --module runc

# 執行修復
kubectl create job --from=cronjob/k8s-sentinel \
  sentinel-fix-$(date +%s) -n kube-system \
  -- fix --module runc --nodes worker1,worker2
```

---

## 📁 目錄結構

```text
60_apps/k8s-sentinel/
├── README.md                           # 本檔案
├── manifests/
│   ├── rbac.yaml                       # ServiceAccount + ClusterRole
│   ├── cronjob.yaml                    # 定期執行的 CronJob
│   ├── 1password-items.yaml            # Secrets 管理
│   └── examples/
│       └── manual-job.example.yaml     # 手動觸發範例
├── scripts/
│   ├── checks/                         # 檢查模組
│   │   ├── __init__.py
│   │   ├── base.py                     # 基礎類
│   │   └── runc_check.py               # runc 檢查
│   │   └── disk_check.py               # disk / ephemeral 檢查
│   ├── fixers/                         # 修復模組
│   │   ├── ansible_fixer.py            # Ansible 執行器
│   │   └── cursor_agent.ts             # Cursor SDK 整合
│   ├── gitops/                         # GitOps 整合
│   │   └── pr_creator.py               # PR 自動化
│   └── main.py                         # 主程式入口
├── Dockerfile                          # Container 映像
└── deploy.sh                           # 部署腳本
```

---

## 🔧 配置

### 環境變數

| 變數 | 說明 | 必需 | 預設值 |
|------|------|------|--------|
| `CURSOR_API_KEY` | Cursor SDK API Key | ❌ | - |
| `GITHUB_TOKEN` | GitHub Personal Access Token | ✅ | - |
| `SENTINEL_MODE` | 執行模式（check/fix） | ❌ | check |
| `SENTINEL_MODULES` | 要執行的模組（逗號分隔） | ❌ | all |
| `SENTINEL_AUTO_FIX` | 是否自動修復 | ❌ | false |
| `SENTINEL_AUTO_PR` | 是否自動建立 PR | ❌ | false |

---

## 📊 監控與日誌

### 查看執行日誌

```bash
# 查看最近的 CronJob 執行
kubectl get jobs -n kube-system -l app=k8s-sentinel --sort-by=.metadata.creationTimestamp

# 查看特定 Job 日誌
kubectl logs -n kube-system job/k8s-sentinel-XXXXXXXX
```

### 監控指標

（Phase 3 實作）

- sentinel_check_total - 檢查執行次數
- sentinel_fix_total - 修復執行次數
- sentinel_fix_success_rate - 修復成功率

---

## 🔐 安全考量

1. **最小權限原則**：
   - Sentinel ServiceAccount 僅有必要的 read 權限
   - 修復操作透過 Ansible（有 audit log）

2. **Secrets 管理**：
   - 所有敏感資訊存放在 1Password
   - 使用 1Password Operator 自動同步

3. **PR Review**：
   - 高風險修復需人工 approve
   - 自動 merge 限制在白名單模組

---

## 📚 相關文檔

- [設計文檔](../../00_docs/planning/K8S_SENTINEL_POD_DESIGN.md) - 完整架構設計
- [PROGRESS_TRACKING.md](../../00_docs/planning/PROGRESS_TRACKING.md) - 實作進度
- [worker-node-runc-troubleshooting.md](../../00_docs/operations/runbooks/worker-node-runc-troubleshooting.md) - runc 故障排除

---

## 📊 Phase 進度

| Phase | 完成度 | 說明 |
|-------|--------|------|
| **1** 基礎框架 | ✅ 100% | CronJob、RBAC、Tekton、deploy |
| **2** 檢查模組 | 🟡 ~85% | 6 模組上線；缺 `resources` |
| **3** 修復 | 🟡 ~60% | Ansible + Pod fix；Cursor 待驗收 |
| **4** GitOps | 🟡 ~50% | `pr_creator` 已修；端到端 PR 待觸發場景 |
| **5** 手動觸發 | 🟡 ~40% | `make cluster-*` 可用；無 kubectl plugin |

### 待辦（優先順序）

1. [公開 repo + Helm](docs/PUBLIC_REPO_PLAN.md) Phase A
2. `make configure-sentinel-registry-mirror`（certs.d）→ 移除 preload DaemonSet
3. Cursor SDK + GitOps PR 端到端驗收
4. `resources` 模組、kubectl plugin、Prometheus metrics

---

## 🚧 開發狀態

### Phase 1: 基礎框架 ✅

- [x] 建立目錄結構、RBAC、CronJob、1Password CR、Dockerfile、`deploy.sh`
- [x] 叢集 CronJob（`kube-system`）
- [x] Tekton release（`make install APP=sentinel`）
- [x] kubelet 映像拉取（ClusterIP + preload / `configure-sentinel-registry-mirror`）

### Phase 2–4: 部分完成 🚧

- [x] 檢查：`runc`、`disk`、`pods`、`components`（叢集 2026-06-08 全綠）
- [x] 修復：Ansible runner、Pod 重啟、Succeeded Pod prune
- [x] GitOps：`pr_creator.py`（分支名 sanitize；無 files 不開 PR）
- [x] `containerd` / `kubelet` 檢查 + `ansible/playbooks/fix-containerd-cri.yml`
- [ ] `resources` 檢查
- [ ] Cursor SDK 端到端驗收

### Phase 5: 手動觸發 🚧

- [x] `make cluster-check` / `cluster-trigger` / `cluster-sentinel.sh`
- [ ] kubectl plugin

詳見 [設計文檔](../../00_docs/planning/K8S_SENTINEL_POD_DESIGN.md)

---

**最後更新**: 2026-06-08（containerd/kubelet 模組、公開 repo 規劃）
**版本**: v0.1.0-dev
