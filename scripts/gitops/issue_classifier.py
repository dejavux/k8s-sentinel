"""Classify whether a pod issue warrants a GitOps PR (manifest) vs runtime-only ops."""

from __future__ import annotations

import re
from typing import Any

# Pending categories that may be fixed by repo manifest changes.
MANIFEST_PENDING_CATEGORIES = frozenset(
    {
        "pvc_unbound",
        "resource_quota",
        "node_affinity",
    }
)

# Container problems that may need manifest / image tag fixes.
MANIFEST_CONTAINER_PROBLEMS = frozenset(
    {
        "ImagePullBackOff",
        "ErrImagePull",
        "CreateContainerConfigError",
        "RunContainerError",
    }
)

# Scheduling / node / CNI / capacity — handle via autoFix, Ansible, or manual ops.
RUNTIME_MESSAGE_PATTERNS = re.compile(
    r"|".join(
        [
            r"unreachable",
            r"not\s+ready",
            r"cni0",
            r"flannel",
            r"sandbox",
            r"network\s+not\s+ready",
            r"connection\s+refused",
            r"no\s+route",
            r"node\s+is\s+cordoned",
            r"disk[\s-]?pressure",
            r"insufficient\s+(cpu|memory|nvidia|gpu|hugepages)",
            r"didn'?t\s+tolerate",
            r"untolerated\s+taint",
        ]
    ),
    re.IGNORECASE,
)


def _combined_text(issue: dict[str, Any]) -> str:
    parts = [
        str(issue.get("scheduling_message") or ""),
        str(issue.get("scheduling_reason") or ""),
        " ".join(issue.get("events") or []),
        str(issue.get("eviction_message") or ""),
        str(issue.get("pending_category") or ""),
    ]
    return " ".join(parts)


def _runtime_only_message(issue: dict[str, Any]) -> bool:
    return bool(RUNTIME_MESSAGE_PATTERNS.search(_combined_text(issue)))


def classify_issue_gitops(issue: dict[str, Any]) -> bool:
    """Return True only when a manifest PR is a reasonable remediation."""
    if issue.get("configmap_mismatch"):
        return True

    problem = str(issue.get("problem") or "")
    if problem == "Pending":
        category = str(issue.get("pending_category") or "unknown")
        if category in {
            "disk_pressure",
            "insufficient_cpu",
            "insufficient_memory",
            "insufficient_resources",
            "taints",
            "node_cordoned",
            "image_pull",
        }:
            return False
        if _runtime_only_message(issue):
            return False
        return category in MANIFEST_PENDING_CATEGORIES

    if problem == "Evicted":
        return False

    if problem == "NotReady":
        return False

    if problem in MANIFEST_CONTAINER_PROBLEMS:
        return not _runtime_only_message(issue)

    if problem in {"CrashLoopBackOff", "Error"}:
        return False

    return False


def aggregate_issues_gitops(issues: list[dict[str, Any]]) -> bool:
    """True when any issue in the list warrants GitOps."""
    return any(classify_issue_gitops(item) for item in issues)
