"""Shared kubectl helpers for node-level checks."""

from __future__ import annotations

import json
import logging
import subprocess
from typing import Any

logger = logging.getLogger(__name__)


def get_nodes_json(label_selector: str | None = None) -> list[dict[str, Any]]:
    """Return node objects from kubectl."""
    cmd = ["kubectl", "get", "nodes", "-o", "json"]
    if label_selector:
        cmd.extend(["-l", label_selector])
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        data = json.loads(proc.stdout)
        return data.get("items", [])
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
    ) as exc:
        logger.error("kubectl get nodes failed: %s", exc)
        return []


def node_ready(node: dict[str, Any]) -> bool:
    """True when Ready condition is True."""
    for cond in node.get("status", {}).get("conditions", []):
        if cond.get("type") == "Ready":
            return cond.get("status") == "True"
    return False


def node_ready_reason(node: dict[str, Any]) -> str:
    """Ready condition reason (e.g. KubeletReady, NodeStatusUnknown)."""
    for cond in node.get("status", {}).get("conditions", []):
        if cond.get("type") == "Ready":
            return str(cond.get("reason", ""))
    return ""


def node_runtime_version(node: dict[str, Any]) -> str:
    """containerRuntimeVersion from node status."""
    return (
        node.get("status", {})
        .get("nodeInfo", {})
        .get("containerRuntimeVersion", "")
        .strip()
    )


def node_schedulable(node: dict[str, Any]) -> bool:
    """False when node is cordoned."""
    return not node.get("spec", {}).get("unschedulable", False)


def node_names(nodes: list[dict[str, Any]]) -> list[str]:
    """Extract metadata.name from node list."""
    return [
        n.get("metadata", {}).get("name", "")
        for n in nodes
        if n.get("metadata", {}).get("name")
    ]
