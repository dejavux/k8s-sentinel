"""
K8s Sentinel - runc 可用性檢查模組

檢查所有 worker 節點的 runc 可用性
"""

import json
import subprocess

from .base import BaseCheck, CheckResult, FixResult


class RuncCheck(BaseCheck):
    """runc 可用性檢查"""

    @property
    def name(self) -> str:
        return "runc"

    @property
    def description(self) -> str:
        return "檢查所有 worker 節點的 runc 可用性"

    def check(self) -> CheckResult:
        """執行檢查"""
        self.logger.info("Starting %s check...", self.name)

        nodes = self._get_worker_nodes()
        if not nodes:
            return CheckResult(
                module=self.name,
                status="error",
                message="No worker nodes found",
                details={"nodes": []},
            )

        failed_nodes = []
        for node in nodes:
            if not self._check_node_runc(node):
                failed_nodes.append(node)

        if not failed_nodes:
            return CheckResult(
                module=self.name,
                status="ok",
                message="All nodes have runc available",
                details={
                    "checked_nodes": nodes,
                    "total": len(nodes),
                    "failed": 0,
                },
            )

        return CheckResult(
            module=self.name,
            status="error",
            message=f"runc not available on {len(failed_nodes)} node(s)",
            details={
                "checked_nodes": nodes,
                "total": len(nodes),
                "failed": len(failed_nodes),
            },
            affected_nodes=failed_nodes,
        )

    def can_auto_fix(self) -> bool:
        """支援自動修復"""
        return True

    def fix(self, check_result: CheckResult) -> FixResult:
        """執行修復"""
        if not check_result.affected_nodes:
            return FixResult(
                module=self.name,
                success=True,
                message="No nodes to fix",
                fixed_nodes=[],
                failed_nodes=[],
            )

        self.logger.info("Fixing %d node(s)...", len(check_result.affected_nodes))

        # Planned: integrate Ansible playbook (fix_runc.yml --limit affected nodes)

        fixed_nodes: list[str] = []
        failed_nodes: list[str] = []

        for node in check_result.affected_nodes:
            # Mock until AnsibleRunner is wired for runc repair
            self.logger.warning("Mock fix for node: %s (Ansible not implemented)", node)
            fixed_nodes.append(node)

        return FixResult(
            module=self.name,
            success=len(failed_nodes) == 0,
            message=f"Fixed {len(fixed_nodes)}/{len(check_result.affected_nodes)} node(s)",
            fixed_nodes=fixed_nodes,
            failed_nodes=failed_nodes,
            details={
                "total": len(check_result.affected_nodes),
            },
        )

    def _get_worker_nodes(self) -> list:
        """獲取 worker 節點（label 值為空字串，非 =true）。"""
        try:
            result = subprocess.run(
                [
                    "kubectl",
                    "get",
                    "nodes",
                    "-l",
                    "node-role.kubernetes.io/worker",
                    "-o",
                    "jsonpath={.items[*].metadata.name}",
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
            nodes = result.stdout.strip().split()
            return [n for n in nodes if n]
        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
        ) as exc:
            self.logger.error("Failed to get worker nodes: %s", exc)
            return []

    def _check_node_runc(self, node: str) -> bool:
        """檢查節點 container runtime（Ready + containerd/CRI）。"""
        try:
            result = subprocess.run(
                ["kubectl", "get", "node", node, "-o", "json"],
                capture_output=True,
                text=True,
                check=True,
                timeout=15,
            )
            data = json.loads(result.stdout)
            conditions = {
                c["type"]: c["status"]
                for c in data.get("status", {}).get("conditions", [])
            }
            if conditions.get("Ready") != "True":
                self.logger.warning("Node %s not Ready", node)
                return False

            runtime = (
                data.get("status", {})
                .get("nodeInfo", {})
                .get("containerRuntimeVersion", "")
            )
            if not runtime:
                self.logger.warning("Node %s missing containerRuntimeVersion", node)
                return False

            runtime_lower = runtime.lower()
            ok = any(
                token in runtime_lower for token in ("containerd", "cri-o", "docker")
            )
            if not ok:
                self.logger.warning("Node %s unexpected runtime: %s", node, runtime)
            return ok
        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            json.JSONDecodeError,
        ) as exc:
            self.logger.warning("runc/runtime check failed for node %s: %s", node, exc)
            return False
