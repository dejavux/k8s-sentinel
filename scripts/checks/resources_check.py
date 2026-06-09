"""
K8s Sentinel - 節點資源壓力檢查（Memory / PID / metrics-server 使用率）

只告警、不自動修復（C2 MVP）。
"""

from __future__ import annotations

import os
import re
import subprocess
from typing import Any

from .base import BaseCheck, CheckResult, FixResult
from .kubectl_nodes import get_nodes_json


def _condition_true(node: dict[str, Any], cond_type: str) -> bool:
    for cond in node.get("status", {}).get("conditions", []):
        if cond.get("type") == cond_type:
            return cond.get("status") == "True"
    return False


def _parse_kubectl_top_nodes() -> dict[str, dict[str, float]]:
    """Return node -> {cpu_percent, memory_percent} from metrics-server."""
    try:
        proc = subprocess.run(
            ["kubectl", "top", "nodes", "--no-headers"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        return {"_error": str(exc)}

    out: dict[str, dict[str, float]] = {}

    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        # NAME  CPU(cores)  CPU(%)  MEMORY(bytes)  MEMORY(%)
        parts = line.split()
        if len(parts) < 5:
            continue
        name = parts[0]
        if len(parts) >= 5:
            cpu_pct = _parse_percent(parts[2])
            mem_pct = _parse_percent(parts[4])
        else:
            cpu_pct = _parse_percent(parts[1])
            mem_pct = _parse_percent(parts[2])
        if cpu_pct is not None and mem_pct is not None:
            out[name] = {"cpu_percent": cpu_pct, "memory_percent": mem_pct}
    return out


def _parse_percent(raw: str) -> float | None:
    m = re.match(r"^(\d+(?:\.\d+)?)%$", raw.strip())
    if not m:
        return None
    return float(m.group(1))


class ResourcesCheck(BaseCheck):
    """Node resource pressure and optional metrics-server utilization."""

    @property
    def name(self) -> str:
        return "resources"

    @property
    def description(self) -> str:
        return "檢查節點 MemoryPressure/PIDPressure 與 metrics-server CPU/記憶體使用率"

    def check(self) -> CheckResult:
        self.logger.info("Starting %s check...", self.name)

        warn_pct = float(os.getenv("SENTINEL_RESOURCE_WARN_PERCENT", "85"))
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
            signals: list[str] = []
            if _condition_true(node, "MemoryPressure"):
                signals.append("MemoryPressure=True")
            if _condition_true(node, "PIDPressure"):
                signals.append("PIDPressure=True")
            if signals:
                issues[name] = {"signals": signals}

        top = _parse_kubectl_top_nodes()
        top_error = top.pop("_error", None)
        for name, stats in top.items():
            cpu = stats.get("cpu_percent", 0.0)
            mem = stats.get("memory_percent", 0.0)
            if cpu >= warn_pct or mem >= warn_pct:
                entry = issues.setdefault(name, {"signals": []})
                if cpu >= warn_pct:
                    entry["signals"].append(f"cpu_usage={cpu}%")
                if mem >= warn_pct:
                    entry["signals"].append(f"memory_usage={mem}%")
                entry["top"] = stats

        affected = sorted(issues.keys())
        details: dict[str, Any] = {
            "checked": len(nodes),
            "warn_percent": warn_pct,
            "nodes": issues,
        }
        if top_error:
            details["metrics_server"] = {"available": False, "error": top_error}
        elif top:
            details["metrics_server"] = {"available": True, "sampled": len(top)}

        if not issues:
            return CheckResult(
                module=self.name,
                status="ok",
                message=f"All {len(nodes)} node(s) within resource thresholds",
                details=details,
            )

        return CheckResult(
            module=self.name,
            status="warning",
            message=f"Resource pressure or high usage on {len(affected)} node(s)",
            details=details,
            affected_nodes=affected,
        )

    def can_auto_fix(self) -> bool:
        return False

    def fix(self, check_result: CheckResult) -> FixResult:
        """Resources module is alert-only."""
        return FixResult(
            module=self.name,
            success=True,
            message="Alert-only module; no automatic fix",
            fixed_nodes=[],
            failed_nodes=check_result.affected_nodes or [],
            details={"skipped": True},
        )
