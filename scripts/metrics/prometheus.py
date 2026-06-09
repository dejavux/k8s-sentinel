"""Optional Prometheus text exposition from Sentinel check results."""

from __future__ import annotations

from typing import Any

_STATUS_VALUE = {"ok": 0, "warning": 1, "error": 2}


def render_prometheus_metrics(
    check_results: dict[str, Any],
) -> str:
    """Build prometheus text format lines from CheckResult-like dicts."""
    lines: list[str] = []
    lines.append("# HELP sentinel_check_status Module check status (0=ok 1=warning 2=error)")
    lines.append("# TYPE sentinel_check_status gauge")

    for module, result in check_results.items():
        status = result.status if hasattr(result, "status") else result.get("status", "ok")
        value = _STATUS_VALUE.get(status, 2)
        lines.append(f'sentinel_check_status{{module="{module}"}} {value}')

    resources = check_results.get("resources")
    if resources is not None:
        details = (
            resources.details
            if hasattr(resources, "details")
            else resources.get("details", {})
        ) or {}
        nodes = details.get("nodes") or {}
        if nodes:
            lines.append("# HELP sentinel_node_resource_pressure 1 if node has resource signals")
            lines.append("# TYPE sentinel_node_resource_pressure gauge")
            for node in nodes:
                lines.append(f'sentinel_node_resource_pressure{{node="{node}"}} 1')
        top_samples = {
            name: info.get("top", {})
            for name, info in nodes.items()
            if info.get("top")
        }
        if top_samples:
            lines.append("# HELP sentinel_node_cpu_usage_percent metrics-server CPU percent")
            lines.append("# TYPE sentinel_node_cpu_usage_percent gauge")
            for node, top in top_samples.items():
                cpu = top.get("cpu_percent")
                if cpu is not None:
                    lines.append(f'sentinel_node_cpu_usage_percent{{node="{node}"}} {cpu}')
            lines.append("# HELP sentinel_node_memory_usage_percent metrics-server memory percent")
            lines.append("# TYPE sentinel_node_memory_usage_percent gauge")
            for node, top in top_samples.items():
                mem = top.get("memory_percent")
                if mem is not None:
                    lines.append(
                        f'sentinel_node_memory_usage_percent{{node="{node}"}} {mem}'
                    )

    return "\n".join(lines) + "\n"
