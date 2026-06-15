"""When Sentinel should open a GitOps PR (Cursor cloud agent)."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from checks.base import CheckResult, FixResult


def gitops_modules() -> frozenset[str]:
    """Modules allowed to trigger GitOps; empty disables auto PR."""
    raw = os.getenv("SENTINEL_GITOPS_MODULES", "pods").strip()
    if not raw or raw.lower() in {"none", "off", "false"}:
        return frozenset()
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def module_needs_gitops(
    module: str,
    check_results: dict[str, CheckResult],
    fix_results: dict[str, FixResult] | None,
) -> bool:
    """True when check/fix metadata marks the module as needing manifest changes."""
    check = check_results.get(module)
    if check is None:
        return False
    details = check.details or {}
    if details.get("needs_gitops"):
        return True
    if fix_results:
        fix = fix_results.get(module)
        if fix and fix.details and fix.details.get("needs_gitops"):
            return True
    return False


def should_create_fix_pr(
    check_results: dict[str, CheckResult],
    fix_results: dict[str, FixResult] | None,
) -> bool:
    """Return True when GitOps PR should be opened."""
    if os.getenv("SENTINEL_AUTO_PR", "false").lower() != "true":
        return False

    allowed = gitops_modules()
    if not allowed:
        return False

    for module in allowed:
        if module_needs_gitops(module, check_results, fix_results):
            return True
    return False
