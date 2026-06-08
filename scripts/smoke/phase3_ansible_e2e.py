#!/usr/bin/env python3
"""Phase 3 AnsibleRunner E2E — run from infra-bootstrap repo root."""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path


def main() -> int:
    """Run AnsibleRunner ephemeral prune dry-run against a limited worker set."""
    repo_root = Path(__file__).resolve().parents[4]
    scripts = repo_root / "60_apps/k8s-sentinel/scripts"
    sys.path.insert(0, str(scripts))
    os.environ["SENTINEL_INFRA_ROOT"] = str(repo_root)
    os.environ.setdefault(
        "ANSIBLE_INVENTORY", str(repo_root / "40_k8s/inventory/hosts.yml")
    )

    ansible_mod = importlib.import_module("fixers.ansible_runner")
    runner = ansible_mod.AnsibleRunner(repo_root)
    limit = os.getenv("SENTINEL_PHASE3_E2E_LIMIT", "worker7").split(",")
    dry_run = os.getenv("SENTINEL_PHASE3_E2E_DRY_RUN", "true").lower() == "true"

    print(f"→ prune_ci_node_ephemeral limit={limit} dry_run={dry_run}")
    result = runner.prune_ci_node_ephemeral(limit, dry_run=dry_run)
    print(f"success={result.success} rc={result.returncode} msg={result.message}")
    if result.stdout:
        print("--- stdout (tail) ---")
        print(result.stdout[-2000:])
    if result.stderr:
        print("--- stderr (tail) ---")
        print(result.stderr[-1000:])
    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())
