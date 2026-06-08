"""
K8s Sentinel - kubelet 健康檢查

偵測節點 NotReady、kubelet 未 active、節點被 cordon 但長期未恢復。
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
    node_schedulable,
)


class KubeletCheck(BaseCheck):
    """kubelet 服務與節點 Ready 檢查"""

    @property
    def name(self) -> str:
        return "kubelet"

    @property
    def description(self) -> str:
        return "檢查節點 kubelet（Ready 狀態、systemd、uncordon）"

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
        cordoned: list[str] = []

        for node in nodes:
            name = node.get("metadata", {}).get("name", "")
            if not name:
                continue
            ready = node_ready(node)
            reason = node_ready_reason(node)
            schedulable = node_schedulable(node)

            if not schedulable:
                cordoned.append(name)

            unhealthy = not ready or reason in {
                "NodeStatusUnknown",
                "KubeletNotReady",
            }
            if unhealthy:
                issues[name] = {
                    "ready": ready,
                    "ready_reason": reason,
                    "schedulable": schedulable,
                    "signals": self._signals(ready, reason, schedulable),
                }

        if os.getenv("SENTINEL_KUBELET_SSH_PROBE", "false").lower() == "true":
            probe = AnsibleRunner().probe_systemd(
                "kubelet", list(issues.keys()) or node_names(nodes)
            )
            for host, state in probe.items():
                if state != "active" and host in issues:
                    issues[host]["systemd"] = state
                elif state != "active":
                    issues[host] = {
                        "ready": node_ready(
                            next(
                                n
                                for n in nodes
                                if n.get("metadata", {}).get("name") == host
                            )
                        ),
                        "systemd": state,
                        "signals": [f"kubelet systemd={state}"],
                    }

        if not issues:
            msg = f"All {len(nodes)} node(s) kubelet Ready"
            if cordoned:
                msg += f" ({len(cordoned)} cordoned)"
            return CheckResult(
                module=self.name,
                status="ok",
                message=msg,
                details={"checked": len(nodes), "cordoned": cordoned},
            )

        affected = sorted(issues.keys())
        return CheckResult(
            module=self.name,
            status="error",
            message=f"kubelet unhealthy on {len(affected)} node(s)",
            details={"issues": issues, "cordoned": cordoned, "checked": len(nodes)},
            affected_nodes=affected,
        )

    def can_auto_fix(self) -> bool:
        return True

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
        restart = runner.restart_systemd_service(
            "kubelet", limit=check_result.affected_nodes
        )
        uncordon = runner.uncordon_nodes(check_result.affected_nodes)

        success = restart.success and uncordon.success
        return FixResult(
            module=self.name,
            success=success,
            message=(
                f"kubelet restart: {restart.message}; uncordon: {uncordon.message}"
            ),
            fixed_nodes=list(check_result.affected_nodes) if success else [],
            failed_nodes=[] if success else list(check_result.affected_nodes),
            details={
                "restart_stdout": restart.stdout,
                "uncordon_stdout": uncordon.stdout,
            },
        )

    @staticmethod
    def _signals(ready: bool, reason: str, schedulable: bool) -> list[str]:
        out: list[str] = []
        if not ready:
            out.append(f"NotReady ({reason or 'unknown'})")
        if not schedulable:
            out.append("SchedulingDisabled (cordoned)")
        return out
