"""
K8s Sentinel - containerd / CRI 健康檢查

偵測 kubelet 無法連線 CRI（如 containerRuntimeVersion=Unknown、
NodeStatusUnknown、journal 中 CRI plugin 載入失敗）。
"""

from __future__ import annotations

import os
from typing import Any

from fixers.ansible_runner import AnsibleRunner

from .base import BaseCheck, CheckResult, FixResult
from .kubectl_nodes import (
    get_nodes_json,
    node_names,
    node_ready,
    node_ready_reason,
    node_runtime_version,
    node_schedulable,
)


class ContainerdCheck(BaseCheck):
    """containerd CRI 可用性檢查"""

    @property
    def name(self) -> str:
        return "containerd"

    @property
    def description(self) -> str:
        return "檢查節點 containerd CRI（Ready、runtime 版本、可選 SSH crictl）"

    def check(self) -> CheckResult:
        self.logger.info("Starting %s check...", self.name)

        nodes = get_nodes_json()
        if not nodes:
            return CheckResult(
                module=self.name,
                status="error",
                message="No nodes returned from API",
            )

        issues: dict[str, dict[str, Any]] = {}
        for node in nodes:
            name = node.get("metadata", {}).get("name", "")
            if not name:
                continue
            detail = self._analyze_node(node)
            if detail.get("unhealthy"):
                issues[name] = detail

        if not issues:
            return CheckResult(
                module=self.name,
                status="ok",
                message=f"All {len(nodes)} node(s) report healthy container runtime",
                details={
                    "checked": len(nodes),
                    "nodes": {n: {"unhealthy": False} for n in node_names(nodes)},
                },
            )

        ansible_cri = self._ansible_cri_failures(list(issues.keys()))
        for host, cri_err in ansible_cri.items():
            if host in issues:
                issues[host]["cri_probe"] = cri_err

        affected = sorted(issues.keys())
        return CheckResult(
            module=self.name,
            status="error",
            message=f"containerd/CRI unhealthy on {len(affected)} node(s)",
            details={"issues": issues, "checked": len(nodes)},
            affected_nodes=affected,
        )

    def can_auto_fix(self) -> bool:
        return os.getenv("SENTINEL_CONTAINERD_ANSIBLE", "true").lower() == "true"

    def fix(self, check_result: CheckResult) -> FixResult:
        if not check_result.affected_nodes:
            return FixResult(
                module=self.name,
                success=True,
                message="No nodes to fix",
                fixed_nodes=[],
                failed_nodes=[],
            )

        runner = AnsibleRunner()
        result = runner.fix_containerd_cri(limit=check_result.affected_nodes)
        if not result.success:
            return FixResult(
                module=self.name,
                success=False,
                message=result.message,
                fixed_nodes=[],
                failed_nodes=list(check_result.affected_nodes),
                details={"ansible": result.stdout, "stderr": result.stderr},
            )

        uncordon = runner.uncordon_nodes(check_result.affected_nodes)
        fixed = list(check_result.affected_nodes) if uncordon.success else []
        failed = [] if uncordon.success else list(check_result.affected_nodes)

        return FixResult(
            module=self.name,
            success=uncordon.success,
            message=(
                f"containerd/kubelet restarted on {len(check_result.affected_nodes)} node(s); "
                f"uncordon: {uncordon.message}"
            ),
            fixed_nodes=fixed,
            failed_nodes=failed,
            details={
                "ansible": result.stdout,
                "uncordon": uncordon.stdout,
            },
        )

    def _analyze_node(self, node: dict[str, Any]) -> dict[str, Any]:
        name = node.get("metadata", {}).get("name", "")
        runtime = node_runtime_version(node)
        ready = node_ready(node)
        reason = node_ready_reason(node)
        runtime_lower = runtime.lower()

        unhealthy = False
        signals: list[str] = []

        if not ready:
            unhealthy = True
            signals.append(f"NotReady ({reason or 'unknown'})")

        if not runtime or "unknown" in runtime_lower:
            unhealthy = True
            signals.append(f"runtime={runtime or 'missing'}")

        if reason == "NodeStatusUnknown":
            unhealthy = True
            signals.append("Kubelet stopped posting status")

        if "cri" in reason.lower() and not ready:
            signals.append("kubelet CRI validation likely failing")

        return {
            "unhealthy": unhealthy,
            "ready": ready,
            "schedulable": node_schedulable(node),
            "runtime": runtime,
            "ready_reason": reason,
            "signals": signals,
        }

    def _ansible_cri_failures(self, nodes: list[str]) -> dict[str, str]:
        """Optional deep probe: crictl info over SSH."""
        if os.getenv("SENTINEL_CONTAINERD_SSH_PROBE", "false").lower() != "true":
            return {}
        runner = AnsibleRunner()
        return runner.probe_crictl(nodes)
