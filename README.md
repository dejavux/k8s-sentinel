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

# kubectl plugin（bin/kubectl-sentinel）：
kubectl sentinel trigger
kubectl sentinel logs --wait
kubectl sentinel check          # trigger + wait + logs
kubectl sentinel check --local  # 本機 python（需 kubeconfig）
kubectl sentinel gitops-e2e     # GitOps 故障注入 smoke
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
| `CURSOR_AGENT_MODEL` | Cursor Agent model（`default`/`auto`=Auto，`composer-2.5`=固定） | 讀 `.env` 或 Helm |
| `CURSOR_MODEL` | 同上 fallback | 同上 |
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
| **2** 檢查模組 | ✅ | 7 模組 prod |
| **3** 修復 | 🟡 ~75% | Ansible + Pod fix；Cursor live E2E 可選 |
| **4** GitOps | 🟡 ~75% | pr_creator + fault-injection smoke |
| **5** 手動觸發 | ✅ | `kubectl sentinel` plugin + `make cluster-*` |

---

## 待辦（repo 視角）

1. ghcr / 公開 repo（C1.2、C3）— 3q 可延後
2. Cursor SDK live E2E（`--with-cursor`）
3. `SENTINEL_PLUGIN_DIR` 外掛目錄

---

## 相關文檔

- [INSTALL_HELM.md](docs/INSTALL_HELM.md)
- [PUBLIC_REPO_PLAN.md](docs/PUBLIC_REPO_PLAN.md)
- infra-bootstrap [K8S_SENTINEL_POD_DESIGN.md](../../00_docs/planning/K8S_SENTINEL_POD_DESIGN.md)
- infra-bootstrap [deploy/k8s-sentinel/TODO.md](../../deploy/k8s-sentinel/TODO.md)

**最後更新**: 2026-06-10 · **叢集版本**: v0.2.4
