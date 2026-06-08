# K8s Sentinel — 公開 Repo 與跨專案整合規劃

**版本**: v0.2.0-plan  
**日期**: 2026-06-08  
**決策（2026-06-08）**：

| 項目 | 決定 |
|------|------|
| Repo | `dejavux/k8s-sentinel`，**先 private**，Phase A 完成後再 public |
| Phase A 優先 | **Helm chart**（已 scaffold：`charts/k8s-sentinel/`） |
| 授權 | **Apache-2.0**（公開時加入 `LICENSE`） |

**目標**: 將 `k8s-sentinel` 抽成獨立 GitHub repo，讓 `infra-bootstrap`、`fuqi-asset-manager` 及其他專案以固定介面安裝與擴充。

---

## 1. 現況與缺口

| 項目 | 現況 | 公開化前需完成 |
|------|------|----------------|
| 核心檢查 | runc / disk / pods / components / **containerd / kubelet** | `resources` 模組、metrics |
| 修復 | Ansible + kubectl uncordon + 內建 playbook | 脫離 infra-bootstrap 硬編路徑 |
| 部署 | `deploy.sh` + CronJob YAML | Helm chart + OCI 映像 |
| Secrets | 1Password Operator（dejavux 專用） | 可選：K8s Secret / ESO / 1Password |
| GitOps | `dejavux/infra-bootstrap` 寫死 | `SENTINEL_GITHUB_REPO` 消費者自訂 |
| 文件 | 設計在 monorepo | 獨立 README + 整合指南 |

---

## 2. 建議 Repo 結構（公開後）

```text
k8s-sentinel/                    # github.com/<org>/k8s-sentinel
├── README.md
├── LICENSE                      # Apache-2.0 或 MIT
├── CHANGELOG.md
├── Dockerfile
├── requirements.txt
├── pyproject.toml               # ruff / pytest 入口
├── ansible/
│   └── playbooks/               # 可攜式修復（fix-containerd-cri 等）
├── scripts/                     # Python 檢查主程式
├── charts/
│   └── k8s-sentinel/            # Helm：CronJob、RBAC、values
├── manifests/                   # 裸 YAML（kubectl apply -k）
│   ├── base/
│   └── overlays/
│       ├── generic/             # 僅 K8s Secret
│       └── onepassword/         # 可選 1Password CR
├── docs/
│   ├── INSTALL.md
│   ├── INTEGRATION.md           # 其他 repo 怎麼接
│   └── MODULES.md
└── .github/
    └── workflows/
        ├── ci.yml               # pytest + lint
        └── release.yml          # ghcr.io 映像 + chart release
```

`infra-bootstrap` 保留薄封裝：

```text
infra-bootstrap/
└── 60_apps/k8s-sentinel/        # git submodule 或 vendor 目錄
    └── Makefile / tekton        # 叢集專用 overlay + inventory ConfigMap
```

---

## 3. 消費者整合方式（其他 repo 怎麼用）

### 3.1 最快：Helm（推薦）

```bash
helm repo add k8s-sentinel https://<org>.github.io/k8s-sentinel
helm upgrade --install k8s-sentinel k8s-sentinel/k8s-sentinel \
  -n kube-system \
  --set image.repository=ghcr.io/<org>/k8s-sentinel \
  --set image.tag=v0.2.0 \
  --set config.modules="runc,disk,pods,components,containerd,kubelet" \
  --set gitops.enabled=false \
  --set ansible.enabled=true \
  --set-file ansible.inventory=./my-cluster/hosts.yml
```

**values 重點**：

| values 路徑 | 用途 |
|-------------|------|
| `config.modules` | 啟用哪些檢查 |
| `config.autoFix` | 是否自動修復 |
| `ansible.enabled` | 是否掛 inventory + SSH secret |
| `ansible.inventory` | 消費者自己的 `hosts.yml` |
| `gitops.repo` | 修復 PR 目標 repo（可為消費者 infra repo） |
| `secrets.existingSecret` | 不用 1Password 時直接引用 Secret |

### 3.2 Git Submodule（單 repo 多環境）

```bash
# 在 fuqi-asset-manager 或自家 infra repo
git submodule add https://github.com/<org>/k8s-sentinel.git tools/k8s-sentinel
kubectl apply -k tools/k8s-sentinel/manifests/overlays/generic
```

### 3.3 OCI 映像 + 上游 CronJob

僅引用映像，manifest 自己維護：

```yaml
image: ghcr.io/<org>/k8s-sentinel:v0.2.0
env:
  - name: SENTINEL_PACKAGE_ROOT
    value: "/app"
  - name: ANSIBLE_INVENTORY
    value: "/ansible/inventory/hosts.yml"
```

### 3.4 擴充檢查模組（Plugin 介面）

公開後維持 `BaseCheck` + `CheckRegistry.register()`；消費者可：

1. **Fork** 加自訂 check（例如 GPU、registry 502）
2. **ConfigMap 掛載** 額外 Python（v0.3+ 規劃：`SENTINEL_PLUGIN_DIR`）
3. **Webhook**：check 失敗 POST 到 Slack/PagerDuty（v0.3+）

---

## 4. 與 infra-bootstrap 脫鉤清單

公開前必須移除或參數化：

| 硬編碼 | 改為 |
|--------|------|
| `SENTINEL_INFRA_ROOT=/workspace/infra-bootstrap` | 可選；僅 disk 等需外部 playbook 時設定 |
| `SENTINEL_GITHUB_REPO=dejavux/infra-bootstrap` | `values.gitops.repo` |
| `40_k8s/inventory/hosts.yml` | ConfigMap 由消費者提供 |
| `60_apps/tekton-ci/scripts/prune-ci-node-ephemeral.sh` | 移到 `k8s-sentinel/ansible/` 或 optional hook |
| `10_baremetal/playbooks/...` | optional `SENTINEL_DISK_PLAYBOOK` |
| `dejavux/k8s-sentinel` 映像 | `ghcr.io/<org>/k8s-sentinel` |
| 1Password `Infra-CI` vault | overlay `generic` 用 K8s Secret |

**已完成（本輪）**：

- `ansible/playbooks/fix-containerd-cri.yml` 隨 repo 發布
- `SENTINEL_PACKAGE_ROOT` / `SENTINEL_PLAYBOOKS_DIR` 解析 playbook 路徑

---

## 5. 分階段時程

### Phase A — 可公開 MVP（1–2 週）

- [x] containerd / kubelet 檢查 + fix playbook
- [x] Helm chart `charts/k8s-sentinel`（values 預設 check-only；`values-3q-prod.yaml` overlay）
- [x] `docs/INSTALL_HELM.md`
- [ ] 建立 **private** repo `dejavux/k8s-sentinel`（subtree / push）
- [ ] `manifests/overlays/generic`（無 1Password 的 kustomize，可選）
- [ ] CI：pytest + ruff + 映像 push `ghcr.io`
- [ ] LICENSE（Apache-2.0）+ SECURITY.md — **公開當天**
- [ ] infra-bootstrap `make install APP=sentinel` 改 helm wrapper

**交付物**：任何人 `helm install` 即可跑 check-only。

### Phase B — 跨 repo 友善（2–3 週）

- [ ] Helm values 完整文件 + `examples/fuqi-asset-manager/`
- [ ] `examples/infra-bootstrap/`（1Password overlay + Tekton 建置）
- [ ] GitHub Release：映像 + chart `.tgz`
- [ ] infra-bootstrap 改為 submodule / `helm dependency` 引用
- [ ] Cursor GitOps 改為 optional component

**交付物**：fuqi / grid-bot 僅需維護 inventory + values，不 fork 核心程式。

### Phase C — 社群化（1 個月+）

- [ ] `resources` 檢查、Prometheus metrics
- [ ] kubectl plugin（`kubectl sentinel check`）
- [ ] Plugin 目錄 `SENTINEL_PLUGIN_DIR`
- [ ] Artifact Hub 上架 Helm chart
- [ ] 英文 README（雙語）

---

## 6. 公開 Repo 命名與授權建議

| 項目 | 建議 |
|------|------|
| Repo 名 | `k8s-sentinel` |
| Org | 個人 `dejavux` 或獨立 org `3q-fi` |
| License | **Apache-2.0**（與 K8s 生態一致） |
| 映像 | `ghcr.io/<org>/k8s-sentinel:<semver>` |
| Chart | `oci://ghcr.io/<org>/charts/k8s-sentinel` |
| 敏感預設 | `autoFix=false`、`autoPR=false`（公開版安全預設） |

---

## 7. infra-bootstrap 遷移步驟（操作清單）

1. **建立** `github.com/<org>/k8s-sentinel`（public）
2. **推送** 目前 `60_apps/k8s-sentinel/` 內容 + 本規劃文件
3. **設定** GitHub Actions → ghcr 映像 + chart release
4. **infra-bootstrap**：
   - `git submodule add` 或刪目錄改 `helm install -f values-3q.yaml`
   - `make install APP=sentinel` 改為 `helm upgrade` wrapper
   - Tekton pipeline 改 build 上游 Dockerfile
5. **驗收**：CronJob 6 模組全綠；模擬 containerd CRI 故障可自動修復
6. **公告**：README 連結公開 repo；monorepo 路徑標 `@deprecated use submodule`

---

## 8. 其他 Repo 最小整合範例

### fuqi-asset-manager（僅監控、不 GitOps）

```yaml
# deploy/k8s/k8s-sentinel-values.yaml
config:
  modules: runc,disk,pods,containerd
  autoFix: true
gitops:
  enabled: false
ansible:
  enabled: false   # 無 SSH 時僅 API 層檢查
```

### grid-bot / 自建 infra（完整修復）

```yaml
ansible:
  enabled: true
  inventoryConfigMap: grid-bot-ansible-inventory
  sshSecret: k8s-sentinel-ansible-ssh
gitops:
  enabled: true
  repo: dejavux/grid-bot-infra
```

---

## 9. 下一步

1. ~~Org / 授權~~ → `dejavux/k8s-sentinel` private + Apache-2.0  
2. ~~Phase A Helm~~ → chart 已 scaffold；待 push private repo + 叢集 `helm upgrade` 驗收  
3. 公開前：`LICENSE`、CI ghcr、將 repo visibility 改 public  

詳見 [INSTALL_HELM.md](INSTALL_HELM.md)。
