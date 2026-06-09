# K8s Sentinel — 自動化叢集健康檢查與修復

**狀態**: 🟢 3q 生產運作中（v0.2.3 · 6 模組）  
**程式 repo**: [dejavux/k8s-sentinel](https://github.com/dejavux/k8s-sentinel)（private submodule）  
**3q 部署**: infra-bootstrap `deploy/k8s-sentinel/` + `make deploy APP=sentinel`  
**公開化規劃**: [docs/PUBLIC_REPO_PLAN.md](docs/PUBLIC_REPO_PLAN.md)

---

## 概述

K8s Sentinel 以 CronJob 定期掃描 Kubernetes 叢集，整合 Ansible 修復與 GitOps PR：

- 每 30 分鐘自動檢查（可手動 trigger）
- host 層修復：Ansible + SSH（3q overlay 使用 `hostNetwork`）
- 叢集內修復：Pod 重啟、Succeeded Pod 清理
- GitOps：修復後開 PR（`SENTINEL_MAX_OPEN_PRS` 防重複）

---

## 功能模組

| 模組 | 檢查項目 | 自動修復 | 3q prod |
|------|---------|---------|---------|
| `runc` | runc 可用性 | ✅ Ansible | ✅ |
| `disk` | DiskPressure / host rootfs | ✅ Ansible + CI 清理 | ✅ |
| `containerd` | CRI Unknown、NodeStatusUnknown | ✅ fix-containerd-cri | ✅ |
| `kubelet` | NotReady、uncordon | ✅ systemctl | ✅ |
| `pods` | 異常 Pod 狀態 | ✅ 叢集內 + GitOps PR | ✅ |
| `components` | kube-proxy、CoreDNS 等 | ✅ Pod 重啟 | ✅ |
| `resources` | Memory/PID pressure、`kubectl top` | ❌ 僅告警 | ⏳ v0.2.4+ |

`resources` 與 Prometheus text metrics 已合入 main（`4e370d0`）；叢集待 v0.2.4 deploy 後啟用。

---

## 快速開始

### 3q 叢集（infra-bootstrap）

```bash
make sync-submodules
make deploy APP=sentinel TAG=v0.2.3      # 僅 Helm
make install APP=sentinel TAG=v0.2.4   # Tekton build + deploy（含 resources 時改 values）
```

詳見 infra-bootstrap [`deploy/k8s-sentinel/README.md`](../../deploy/k8s-sentinel/README.md)（路徑相對 submodule 根目錄可能需調整；以 monorepo 根為準）。

### Helm（通用）

```bash
helm upgrade --install k8s-sentinel ./charts/k8s-sentinel -n kube-system
```

見 [docs/INSTALL_HELM.md](docs/INSTALL_HELM.md)。

### 手動觸發

```bash
kubectl create job --from=cronjob/k8s-sentinel sentinel-check-$(date +%s) -n kube-system
# infra-bootstrap：
make cluster-trigger && make cluster-logs
```

---

## 目錄結構

```text
k8s-sentinel/
├── charts/k8s-sentinel/     # Helm（CronJob、RBAC、values）
├── scripts/
│   ├── checks/              # 檢查模組（BaseCheck + registry）
│   ├── fixers/              # Ansible runner
│   ├── gitops/              # pr_creator、repo_bootstrap
│   ├── metrics/             # Prometheus text exposition
│   └── main.py
├── ansible/playbooks/       # fix-containerd-cri 等
├── tekton/                  # release pipeline
├── docs/
└── manifests/               # 裸 YAML（DEPRECATED，優先 Helm）
```

---

## 配置（環境變數）

| 變數 | 說明 | 預設 |
|------|------|------|
| `SENTINEL_MODULES` | 模組列表（逗號分隔） | chart values |
| `SENTINEL_AUTO_FIX` | 自動修復 | false（公開 chart） |
| `SENTINEL_MAX_OPEN_PRS` | 同 repo 最多 open fix PR | 1 |
| `SENTINEL_OUTPUT_FILE` | JSON 結果路徑 | `/workspace/sentinel-results.json` |
| `SENTINEL_METRICS_FILE` | Prometheus text 輸出（可選） | — |
| `GITHUB_TOKEN` | GitOps PR | Secret |
| `SENTINEL_GITHUB_REPO` | PR 目標 repo | 消費者自訂 |

---

## 監控

### 日誌

```bash
kubectl get jobs -n kube-system -l app.kubernetes.io/name=k8s-sentinel
kubectl logs -n kube-system job/k8s-sentinel-XXXXXXXX
```

### Metrics（C2，可選）

設定 `SENTINEL_METRICS_FILE` 後，每次 check 寫入 Prometheus text exposition，例如：

- `sentinel_check_status{module="disk"}`
- `sentinel_node_memory_usage_percent{node="worker1"}`

Helm chart 尚未暴露 `metricsFile` values；v0.2.4 前可手動 patch CronJob env。

---

## CI（C1.1）

GitHub Actions：push/PR → main 執行 **pytest** + **ruff**。

```bash
make test       # 15 tests
make lint-ci
```

Workflow：`.github/workflows/ci.yml`

---

## Phase 進度

| Phase | 完成度 | 說明 |
|-------|--------|------|
| **1** 基礎框架 | ✅ | CronJob、RBAC、Tekton、Helm、deploy wrapper |
| **2** 檢查模組 | 🟢 ~95% | 7 模組程式完成；prod 仍 6 模組 |
| **3** 修復 | 🟡 ~70% | Ansible + Pod fix 上線；Cursor 待 E2E |
| **4** GitOps | 🟡 ~65% | pr_creator + dedup；需故障場景驗 PR |
| **5** 手動觸發 | 🟡 ~50% | `make cluster-*`；無 kubectl plugin |

---

## 待辦（repo 視角）

1. v0.2.4 release + 3q 啟用 `resources`
2. Helm：`config.metricsFile` → `SENTINEL_METRICS_FILE`
3. ghcr / 公開 repo（C1.2、C3）— 3q 可延後
4. Cursor SDK E2E、kubectl plugin、plugin 目錄

---

## 相關文檔

- [INSTALL_HELM.md](docs/INSTALL_HELM.md)
- [PUBLIC_REPO_PLAN.md](docs/PUBLIC_REPO_PLAN.md)
- infra-bootstrap [K8S_SENTINEL_POD_DESIGN.md](../../00_docs/planning/K8S_SENTINEL_POD_DESIGN.md)
- infra-bootstrap [deploy/k8s-sentinel/TODO.md](../../deploy/k8s-sentinel/TODO.md)

**最後更新**: 2026-06-09 · **叢集版本**: v0.2.3 · **main HEAD**: 含 C2 MVP
