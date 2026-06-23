# K8s Sentinel Pod 設計文檔

**建立日期**: 2026-05-21 · **遷入本 repo**: 2026-06-22（自 infra-bootstrap `00_docs/planning/`）
**狀態**: 🟢 MVP 運作中（CronJob 穩定；Phase 5 / 部分模組 / GitOps 端到端待做）
**consumer 部署**: infra-bootstrap [`deploy/k8s-sentinel/README.md`](https://github.com/dejavux/infra-bootstrap/blob/main/deploy/k8s-sentinel/README.md)
**待辦**: infra-bootstrap [`deploy/k8s-sentinel/TODO.md`](https://github.com/dejavux/infra-bootstrap/blob/main/deploy/k8s-sentinel/TODO.md)

---

## 🎯 目標

建立一個自動化的 Kubernetes 叢集健康檢查與修復系統（Sentinel），能夠：

1. **固定掃描**：CronJob 定期檢查叢集健康狀態
2. **自動修復**：整合 Cursor SDK + Cloud Agent 處理常見問題
3. **模組化**：支援手動觸發特定修復模組
4. **GitOps 整合**：修復後自動提交 PR 並 merge 回 main

---

## 🏗️ 架構設計

### 核心組件

```text
┌─────────────────────────────────────────────────────────────┐
│                    K8s Sentinel System                       │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌────────────────┐         ┌──────────────────┐            │
│  │  CronJob       │────────>│  Sentinel Pod    │            │
│  │  (定期觸發)     │         │  (檢查 + 修復)    │            │
│  └────────────────┘         └──────────────────┘            │
│         │                            │                       │
│         │                            ├──> 檢查模組           │
│         │                            │    • runc 可用性      │
│         │                            │    • containerd 健康  │
│         │                            │    • kubelet 狀態     │
│         │                            │    • Pod 異常         │
│         │                            │    • 資源使用         │
│         │                            │                       │
│         │                            ├──> 修復模組           │
│         │                            │    • Ansible 執行     │
│         │                            │    • Cursor SDK       │
│         │                            │    • Cloud Agent      │
│         │                            │                       │
│         │                            └──> GitOps 整合        │
│         │                                 • 生成修復腳本      │
│         │                                 • 提交 PR          │
│         │                                 • Auto merge       │
│         │                                                    │
│  ┌────────────────┐         ┌──────────────────┐            │
│  │  Manual Job    │────────>│  手動觸發模組     │            │
│  │  (kubectl)     │         │  --module runc   │            │
│  └────────────────┘         └──────────────────┘            │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

---

## 📦 實作規劃

### Phase 1: 基礎框架（2-3 天）

#### 1.1 CronJob 定義

```yaml
# 60_apps/k8s-sentinel/manifests/cronjob.yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: k8s-sentinel
  namespace: kube-system
spec:
  schedule: "*/30 * * * *"  # 每 30 分鐘
  concurrencyPolicy: Forbid
  jobTemplate:
    spec:
      template:
        spec:
          serviceAccountName: k8s-sentinel
          restartPolicy: OnFailure
          containers:
          - name: sentinel
            image: dejavux/k8s-sentinel:v0.1.0
            env:
            - name: CURSOR_API_KEY
              valueFrom:
                secretKeyRef:
                  name: k8s-sentinel-secrets
                  key: cursor-api-key
            - name: GITHUB_TOKEN
              valueFrom:
                secretKeyRef:
                  name: k8s-sentinel-secrets
                  key: github-token
            volumeMounts:
            - name: infra-repo
              mountPath: /workspace/infra-bootstrap
          volumes:
          - name: infra-repo
            emptyDir: {}
```

#### 1.2 RBAC 設定

```yaml
# 60_apps/k8s-sentinel/manifests/rbac.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: k8s-sentinel
  namespace: kube-system
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: k8s-sentinel
rules:
- apiGroups: [""]
  resources: ["nodes", "pods", "events"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["pods/log"]
  verbs: ["get"]
- apiGroups: ["apps"]
  resources: ["deployments", "daemonsets", "statefulsets"]
  verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: k8s-sentinel
subjects:
- kind: ServiceAccount
  name: k8s-sentinel
  namespace: kube-system
roleRef:
  kind: ClusterRole
  name: k8s-sentinel
  apiGroup: rbac.authorization.k8s.io
```

#### 1.3 Secrets 管理（1Password）

```yaml
# 60_apps/k8s-sentinel/manifests/1password-items.yaml
apiVersion: onepassword.com/v1
kind: OnePasswordItem
metadata:
  name: k8s-sentinel-secrets
  namespace: kube-system
spec:
  itemPath: "vaults/Infra-CI/items/k8s-sentinel-credentials"
```

---

### Phase 2: 檢查模組（3-5 天）

#### 2.1 核心檢查器

```python
# scripts/sentinel/checks/__init__.py
from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from dataclasses import dataclass

@dataclass
class CheckResult:
    """檢查結果"""
    module: str
    status: str  # "ok" | "warning" | "critical"
    message: str
    affected_nodes: List[str]
    suggested_fix: Optional[str] = None
    metadata: Dict = None

class HealthCheck(ABC):
    """健康檢查基礎類"""

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def check(self) -> CheckResult:
        pass

    @abstractmethod
    def can_auto_fix(self) -> bool:
        pass
```

#### 2.2 runc 檢查模組

```python
# scripts/sentinel/checks/runc_check.py
import subprocess
from typing import List, Dict
from .base import HealthCheck, CheckResult

class RuncHealthCheck(HealthCheck):
    """檢查所有節點的 runc 可用性"""

    @property
    def name(self) -> str:
        return "runc-availability"

    def check(self) -> CheckResult:
        """執行檢查"""
        # 1. 取得所有節點
        nodes = self._get_all_nodes()

        # 2. 檢查每個節點的 runc
        failed_nodes = []
        for node in nodes:
            if not self._check_node_runc(node):
                failed_nodes.append(node)

        if not failed_nodes:
            return CheckResult(
                module=self.name,
                status="ok",
                message="所有節點 runc 正常",
                affected_nodes=[]
            )

        return CheckResult(
            module=self.name,
            status="critical",
            message=f"{len(failed_nodes)} 個節點缺少 runc",
            affected_nodes=failed_nodes,
            suggested_fix="ansible-playbook playbooks/maintenance/ensure_runc_gpu_workers.yml",
            metadata={"nodes": failed_nodes}
        )

    def _get_all_nodes(self) -> List[str]:
        """取得所有節點名稱"""
        result = subprocess.run(
            ["kubectl", "get", "nodes", "-o", "jsonpath={.items[*].metadata.name}"],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.split()

    def _check_node_runc(self, node: str) -> bool:
        """檢查單一節點的 runc"""
        # 透過 debug pod 或 SSH 檢查
        try:
            # 建立 debug pod
            result = subprocess.run(
                [
                    "kubectl", "debug", f"node/{node}",
                    "-it", "--image=alpine",
                    "--", "chroot", "/host", "which", "runc"
                ],
                capture_output=True,
                text=True,
                timeout=30
            )
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            return False

    def can_auto_fix(self) -> bool:
        return True
```

#### 2.3 其他檢查模組

```python
# scripts/sentinel/checks/containerd_check.py
class ContainerdHealthCheck(HealthCheck):
    """檢查 containerd 服務狀態"""
    pass

# scripts/sentinel/checks/pod_check.py
class PodHealthCheck(HealthCheck):
    """檢查 Pod 異常狀態（CrashLoopBackOff / ImagePullBackOff）"""
    pass

# scripts/sentinel/checks/resource_check.py
class ResourceHealthCheck(HealthCheck):
    """檢查節點資源使用率"""
    pass
```

---

### Phase 3: 修復模組（5-7 天）

#### 3.1 Cursor SDK 整合

```typescript
// scripts/sentinel/fixers/cursor-agent.ts
import { Agent } from "@cursor/sdk";
import { CheckResult } from "../checks/base";

export class CursorFixer {
  private apiKey: string;

  constructor(apiKey: string) {
    this.apiKey = apiKey;
  }

  async generateFix(check: CheckResult): Promise<string> {
    const prompt = `
你是 Kubernetes 基礎設施專家。根據以下健康檢查結果，生成修復方案：

## 問題
- 模組: ${check.module}
- 狀態: ${check.status}
- 訊息: ${check.message}
- 受影響節點: ${check.affected_nodes.join(", ")}

## 建議修復
${check.suggested_fix || "無"}

## 任務
請生成：
1. Ansible playbook 或腳本來修復此問題
2. 驗證修復是否成功的測試步驟
3. 相關文檔更新（如需要）

輸出格式為 JSON：
{
  "fix_type": "ansible|script|manual",
  "fix_content": "...",
  "verification": "...",
  "docs_update": "..."
}
`;

    const result = await Agent.prompt(prompt, {
      apiKey: this.apiKey,
      model: { id: "composer-2" },
    });

    if (result.status !== "finished" || !result.result) {
      throw new Error("Cursor Agent 未返回結果");
    }

    return result.result;
  }
}
```

#### 3.2 Ansible 執行器

```python
# scripts/sentinel/fixers/ansible_fixer.py
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, Optional

class AnsibleFixer:
    """執行 Ansible 修復"""

    def __init__(self, repo_path: Path):
        self.repo_path = repo_path
        self.k8s_path = repo_path / "40_k8s"

    def fix_runc(self, nodes: list[str]) -> Dict:
        """修復 runc 問題"""
        # 執行 Ansible playbook
        result = subprocess.run(
            [
                "ansible-playbook",
                "-i", "inventory/hosts.yml",
                "playbooks/maintenance/ensure_runc_gpu_workers.yml",
                "--limit", ",".join(nodes)
            ],
            cwd=self.k8s_path,
            capture_output=True,
            text=True
        )

        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr
        }

    def create_fix_playbook(self, content: str) -> Path:
        """動態建立修復 playbook"""
        tmp_file = tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.yml',
            delete=False,
            dir=self.k8s_path / "playbooks" / "maintenance"
        )
        tmp_file.write(content)
        tmp_file.close()
        return Path(tmp_file.name)
```

---

### Phase 4: GitOps 整合（3-5 天）

#### 4.1 自動 PR 流程

```python
# scripts/sentinel/gitops/pr_creator.py
import subprocess
from pathlib import Path
from datetime import datetime

class GitOpsPRCreator:
    """自動建立並 merge PR"""

    def __init__(self, repo_path: Path, github_token: str):
        self.repo_path = repo_path
        self.github_token = github_token

    def create_fix_pr(
        self,
        fix_content: str,
        check_result: Dict,
        fix_result: Dict
    ) -> str:
        """建立修復 PR"""
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        branch_name = f"sentinel/fix-{check_result['module']}-{timestamp}"

        # 1. 建立分支
        subprocess.run(
            ["git", "checkout", "-b", branch_name],
            cwd=self.repo_path,
            check=True
        )

        # 2. 寫入修復內容
        self._write_fix_files(fix_content, check_result)

        # 3. Commit
        commit_msg = self._generate_commit_message(check_result, fix_result)
        subprocess.run(
            ["git", "add", "-A"],
            cwd=self.repo_path,
            check=True
        )
        subprocess.run(
            ["git", "commit", "-m", commit_msg],
            cwd=self.repo_path,
            check=True
        )

        # 4. Push
        subprocess.run(
            ["git", "push", "-u", "origin", branch_name],
            cwd=self.repo_path,
            check=True
        )

        # 5. 建立 PR
        pr_url = self._create_github_pr(branch_name, check_result, fix_result)

        # 6. Auto merge（若啟用）
        if self._should_auto_merge(check_result):
            self._merge_pr(pr_url)

        return pr_url

    def _write_fix_files(self, fix_content: str, check_result: Dict):
        """寫入修復檔案"""
        # 依據 fix_type 寫入對應位置
        # - ansible playbook → 40_k8s/playbooks/maintenance/
        # - script → scripts/sentinel/fixes/
        # - documentation → 00_docs/operations/runbooks/
        pass

    def _generate_commit_message(
        self,
        check_result: Dict,
        fix_result: Dict
    ) -> str:
        """生成 commit message"""
        return f"""fix(sentinel): 自動修復 {check_result['module']}

## 問題
- {check_result['message']}
- 受影響節點: {', '.join(check_result['affected_nodes'])}

## 修復
{fix_result.get('summary', '執行自動修復腳本')}

## 驗證
- [x] Sentinel 自動檢查通過
- [x] 受影響節點已恢復正常

由 K8s Sentinel 自動生成
"""

    def _should_auto_merge(self, check_result: Dict) -> bool:
        """判斷是否自動 merge"""
        # 僅自動 merge 低風險修復
        auto_merge_modules = [
            "runc-availability",
            "containerd-restart"
        ]
        return check_result['module'] in auto_merge_modules
```

---

### Phase 5: 手動觸發模組（2-3 天）

#### 5.1 kubectl plugin

```bash
# scripts/sentinel/kubectl-sentinel
#!/usr/bin/env bash
# kubectl sentinel 插件

set -euo pipefail

usage() {
  cat <<EOF
kubectl sentinel - K8s Sentinel 管理工具

用法:
  kubectl sentinel check [module]        - 執行健康檢查
  kubectl sentinel fix [module]          - 手動觸發修復
  kubectl sentinel list-modules          - 列出所有模組
  kubectl sentinel logs                  - 查看最近執行日誌

模組:
  runc              - 檢查／修復 runc 可用性
  containerd        - 檢查／修復 containerd 服務
  pods              - 檢查異常 Pod
  resources         - 檢查資源使用率
  all               - 執行所有檢查

範例:
  kubectl sentinel check runc
  kubectl sentinel fix runc --nodes worker1,worker2
  kubectl sentinel fix all --auto-pr
EOF
}

main() {
  case "${1:-}" in
    check)
      sentinel_check "${2:-all}"
      ;;
    fix)
      sentinel_fix "${2:-}" "${@:3}"
      ;;
    list-modules)
      sentinel_list_modules
      ;;
    logs)
      sentinel_logs
      ;;
    *)
      usage
      exit 1
      ;;
  esac
}

sentinel_check() {
  local module="$1"
  kubectl create job --from=cronjob/k8s-sentinel \
    "sentinel-check-$(date +%s)" \
    -n kube-system \
    -- check --module "$module"
}

sentinel_fix() {
  local module="$1"
  shift
  kubectl create job --from=cronjob/k8s-sentinel \
    "sentinel-fix-$(date +%s)" \
    -n kube-system \
    -- fix --module "$module" "$@"
}

main "$@"
```

---

## 📊 模組清單

### 已規劃模組

| 模組名稱 | 檢查項目 | 自動修復 | 優先級 |
|---------|---------|---------|--------|
| `runc` | runc 可用性 | ✅ Ansible | P0 |
| `disk` | DiskPressure / ephemeral-storage | ✅ 叢集內 CI Pod 清理 + Ansible（host） | P0 |
| `containerd` | containerd 服務狀態 | ✅ systemctl restart | P0 |
| `kubelet` | kubelet 服務狀態 | ✅ systemctl restart | P0 |
| `pods` | Pod 異常狀態 | ⚠️ 部分（重啟） | P1 |
| `resources` | CPU/Memory 使用率 | ❌ 僅告警 | P2 |
| `network` | 網路連通性 | ⚠️ 部分 | P1 |
| `storage` | PV/PVC 狀態 | ❌ 僅告警 | P2 |

### `disk` 模組對接（baremetal / CI）

| 層級 | 腳本 / Playbook | Repo | 說明 |
|------|----------------|------|------|
| 叢集內 | `kubectl delete pod … Succeeded` | **infra-bootstrap** `60_apps/k8s-sentinel` | Phase 1 已實作 |
| CI worker | `prune-ci-node-ephemeral.sh` | **infra-bootstrap** `60_apps/tekton-ci/scripts/` | `crictl rmi --prune`；需 SSH |
| baremetal | `deploy_disk_maintenance.yml` | **infra-bootstrap** `10_baremetal/playbooks/` | cron + `system_disk_maintenance.sh` |
| 應用側 | `release stack` 改單獨 target | **fuqi-asset-manager** | 避免五並行壓爆 ephemeral |

### 未來擴充

- GPU 節點健康檢查
- 證書到期檢查
- 備份驗證
- 安全漏洞掃描

---

## 🔐 安全考量

### 1. 權限控制

- Sentinel ServiceAccount 僅有 **read-only** 權限（除修復必需）
- 修復操作需通過 Ansible（有 audit log）
- 自動 merge PR 僅限白名單模組

### 2. Secrets 管理

```yaml
# 使用 1Password Operator
Infra-CI vault:
  - k8s-sentinel-credentials
    - cursor-api-key
    - github-token
    - ansible-vault-password (若需要)
```

### 3. PR Review

- 高風險修復（containerd/kubelet restart）需人工 approve
- 自動 merge 限制在已驗證的修復模組
- 所有修復都有完整 commit message 與驗證步驟

---

## 📅 實作時間表

| Phase | 任務 | 預估時間 | 狀態 |
|-------|------|---------|------|
| Phase 1 | 基礎框架 + CronJob | 2-3 天 | ✅ Tekton build + 叢集 CronJob 穩定 Complete |
| Phase 2 | 檢查模組（runc/containerd/pods） | 3-5 天 | 🚧 4 模組上線；缺 `containerd`/`kubelet`/`resources` |
| Phase 3 | 修復模組 + Cursor SDK | 5-7 天 | 🚧 Ansible + Pod 重啟已接；Cursor SDK 待端到端驗收 |
| Phase 4 | GitOps 整合 | 3-5 天 | 🚧 PR 流程已接；無 manifest 變更時優雅跳過 |
| Phase 5 | 手動觸發 + kubectl plugin | 2-3 天 | 🚧 `make cluster-*`；無 kubectl plugin |
| **總計** | | **15-23 天** | |

---

## 🎯 驗收標準

### MVP（Phase 1-3）

- [x] CronJob 每 30 分鐘自動執行
- [x] 成功檢測 runc（叢集內已驗證）
- [x] 自動執行 Ansible 修復（disk host prune；runc playbook 路徑已接）
- [x] 修復後重跑檢查（`main.py` post-fix pass）
- [ ] Cursor SDK 整合運作（CronJob memory 1.5Gi；曾 OOM；fallback 已 sanitize branch）

### 完整版（Phase 1-5）

- [x] 支援 4 個檢查模組（`runc`/`disk`/`pods`/`components`）
- [x] 叢集 CronJob 連續成功執行（2026-06-08 驗收）
- [ ] 自動建立並 merge PR（程式已接；待 GitOps 場景觸發驗收）
- [ ] kubectl plugin 可手動觸發（現用 `make cluster-trigger`）
- [ ] 完整的 audit log
- [ ] Prometheus metrics 輸出

---

## 📖 相關文檔

- [worker-node-runc-troubleshooting.md](../operations/runbooks/worker-node-runc-troubleshooting.md) - runc 故障排除
- [infra-bootstrap PROGRESS_TRACKING](https://github.com/dejavux/infra-bootstrap/blob/main/00_docs/planning/PROGRESS_TRACKING.md) - consumer 進度
- [deploy/k8s-sentinel/TODO.md](https://github.com/dejavux/infra-bootstrap/blob/main/deploy/k8s-sentinel/TODO.md) - 3q prod 待辦
- Cursor SDK 文檔: <https://docs.cursor.com/sdk>

---

**下一步**：

1. `make configure-sentinel-registry-mirror` 套用全 worker 後移除 preload DaemonSet
2. 實作 `containerd` / `kubelet` / `resources` 檢查模組
3. Cursor SDK + GitOps PR 端到端驗收（含 `GITHUB_TOKEN` / 白名單 merge）
4. kubectl plugin（Phase 5）

**最後更新**: 2026-06-08
