# k8s-sentinel — 公開後宣傳、TA 與 Grant / 合作

**狀態**: 待 repo public 後執行  
**技術前置**: Phase A 完成（LICENSE、generic overlay、ghcr release workflow、脫敏）  
**SSOT 技術規劃**: [PUBLIC_REPO_PLAN.md](./PUBLIC_REPO_PLAN.md)

---

## 1. 定位（電梯 pitch）

**英文（對外）**

> k8s-sentinel is a lightweight CronJob that heals your self-hosted Kubernetes cluster before you wake up — disk pressure, containerd CRI, kube-proxy, and more — with optional Ansible SSH fixes for bare-metal nodes.

**中文（對內）**

> 給 homelab / bare-metal 小團隊的「Prometheus 告警之後的自癒層」，不是 Datadog 替代品。

**不要當主賣點**

- Cursor Agent 自動開 PR（標 experimental）
- 3q 私有叢集細節

---

## 2. 目標受眾（TA）

| 族群 | 痛點 | 為何會 star / install |
|------|------|------------------------|
| **Homelab K8s** | 半夜 node NotReady、disk full | 輕量、自架、Helm 一條命令 |
| **Bare-metal + SSH** | 雲工具修不了 containerd | Ansible host 修復是差異化 |
| **INDIE / 1–3 人 SRE** | 不想付 Robusta/Komodor | CronJob + 可選 autoFix |
| **1Password 用戶** | Secret 管理已有 Connect | optional overlay 可當整合範例 |

**非 TA（勿花力氣）**

- 純託管 EKS/GKE（無 SSH）
- 已有完整 SRE 平台的大團隊
- 需要 SLA 的企業採購

---

## 3. 公開 Checklist（make public 當天）

### 技術（Phase A — 已完成於 repo）

- [x] `LICENSE`（Apache-2.0）
- [x] `SECURITY.md`、`CONTRIBUTING.md`、`CHANGELOG.md`
- [x] Helm 預設 check-only；`examples/helm/` + `manifests/overlays/generic|onepassword`
- [x] `.github/workflows/release.yml` → ghcr.io on tag `v*`
- [x] Python/TS 預設值脫敏（無 infra-bootstrap fallback）
- [x] `node_modules/` 移出版本庫

### 公開當天操作

1. GitHub repo **Settings → Change visibility → Public**
2. 打 tag `v0.2.7`（或下一個 patch）觸發 ghcr release
3. README 首屏確認：install 指令、架構圖、safe defaults
4. GitHub Topics: `kubernetes`, `homelab`, `devops`, `prometheus`, `ansible`, `self-hosted`
5. 確認 **無** open security advisory、無 secret 在 history（`gitleaks` 可選跑全庫）

---

## 4. 宣傳時程（公開後逐步）

### Week 0（公開當天）

| 動作 | 渠道 | 素材 |
|------|------|------|
| 發布 | GitHub Release v0.2.7 | CHANGELOG + chart tgz |
| 短文 | 個人 blog / Dev.to | 《Self-hosted K8s auto-heal without Datadog》 |
| 社群 | r/homelab, r/kubernetes | 問題驅動：「誰在 bare-metal 上自動修 containerd？」 |
| 可選 | Hacker News Show HN | 標題含 **homelab / bare-metal / CronJob** |

### Week 1–2

- 5 分鐘 demo：`kind` 或 `minikube` + `helm install` + 故障注入
- Grafana dashboard 截圖（若 upstream 提供）
- 回覆 GitHub Issues / Discussions

### Month 1+

- Artifact Hub 上架 Helm chart（Phase C）
- 1Password Developer Community 發整合文
- 英文 README 為主、中文 FAQ 可放 `docs/zh-TW/`

### 內容大綱（一篇博文）

```markdown
1. Problem — 凌晨 disk / containerd 掛了
2. Architecture — CronJob → checks → optional Ansible / GitOps
3. Demo — helm install + kubectl sentinel check
4. Safe defaults — autoFix off by default
5. Limitations — 需要 SSH 才 full fix；GitOps experimental
6. Links — repo, INSTALL_HELM, SECURITY
```

---

## 5. Grant / 合作申請

### 5.1 1Password for Open Source — **建議申請** ✅

| 項目 | 內容 |
|------|------|
| 計畫 | [github.com/1Password/for-open-source](https://github.com/1Password/for-open-source) |
| 得到什麼 | 免費 **1Password Teams**（專案 secret，非現金） |
| 資格 | 開源 ≥30 天、Apache-2.0、核心貢獻者、非商業為主 |
| 時機 | **public 後 30 天**再申請 |
| 敘事 | k8s-sentinel 示範 K8s CronJob + 1Password Operator 安全注入 `github-token` / `cursor-api-key` |
| 素材 | `examples/helm/values-onepassword.yaml`、`manifests/overlays/onepassword/` |
| 步驟 | 1) 建 Teams trial 2) 填 [application form](https://github.com/1Password/for-open-source) 開 issue 3) 等審核 |

**額外**：加入 [1Password Developer Slack](https://developer.1password.com/joinslack)，發整合指南帖（非 spam）。

### 5.2 Cursor — **無 OSS grant；改案例合作** ⚠️

| 路徑 | 適合度 | 行動 |
|------|--------|------|
| Open Source grant | ❌ 不存在 | 不申請 |
| Student / Startup | △ | 個人已有 Pro 則非必要 |
| **Ambassador** | △ | 偏社群經營，非 repo 背書 |
| **DevRel / case study** | ✅ | 主推 |

**Cursor 合作 pitch（英文草稿）**

> Reference integration: running Cursor Cloud Agents inside a Kubernetes CronJob to open remediation PRs when checks fail. Reproducible Job manifest + `CURSOR_AGENT_RUNTIME=cloud` documented in repo. Happy to co-author a blog post or docs page.

**聯繫方式**：Cursor forum / support / X @cursor — 附 repo link + E2E 驗收數字（~195s cluster Job）。

**注意**：GitOps 模組標 **experimental**；對外宣傳仍以 bare-metal heal 為主。

### 5.3 其他（低優先）

| 計畫 | 備註 |
|------|------|
| GitHub Sponsors | milestone 穩定後可開 |
| CNCF Sandbox | 過重，暫不考慮 |
| Artifact Hub | Phase C，增加 discoverability |

---

## 6. 成功指標（現實預期）

| 指標 | 3 個月合理目標 |
|------|----------------|
| GitHub Stars | 50–300 |
| 外部 issue/PR | ≥3（代表真採用） |
| ghcr pull | 追蹤 ghcr traffic |
| 1Password OSS | 申請通過 |
| Cursor 回覆 | 1 篇 case study 或 docs 連結 |

---

## 7. 風險與應對

| 風險 | 應對 |
|------|------|
| 「自動刪 pod 太危險」 | 文檔強調 default check-only；production 需 code review 才開 autoFix |
| 維護負擔 | 每月 tag；issue 模板；明確 supported versions（SECURITY.md） |
| 與商業工具比較 | 定位 niche：自架 bare-metal，不拼功能面 |
| Secret 洩漏通報 | SECURITY.md 私人通報流程 |

---

## 8. 執行順序（建議）

```text
Phase A 技術完成 → public repo → tag v0.2.7 → ghcr 首發
    → Week 0 宣傳（blog + Reddit）
    → +30 天 1Password OSS 申請
    → 平行 Cursor case study 投稿
    → Month 1 Artifact Hub（可選）
```

---

## 9. 相關連結

- 安裝：[INSTALL_HELM.md](./INSTALL_HELM.md)
- 技術公開規劃：[PUBLIC_REPO_PLAN.md](./PUBLIC_REPO_PLAN.md)
- 3q 生產 overlay（私有）：infra-bootstrap `deploy/k8s-sentinel/values-3q-prod.yaml`
- 1Password OSS：<https://github.com/1Password/for-open-source>
- Cursor Ambassadors：<https://cursor.com/ambassadors>
