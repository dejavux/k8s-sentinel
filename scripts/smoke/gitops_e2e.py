#!/usr/bin/env python3
"""GitOps E2E: fault-injection payload → generate_pr_meta (fallback / optional Cursor)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# scripts/ on path when run from smoke/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gitops.pr_creator import generate_pr_meta, sanitize_git_branch_slug


def _fault_injection_payload() -> dict:
    """Synthetic pods/components failure resembling production incidents."""
    return {
        "timestamp": "2026-06-10T00:00:00",
        "checks": {
            "pods": {
                "module": "pods",
                "status": "error",
                "message": "3 pod(s) unhealthy",
                "affected_nodes": ["worker2"],
                "details": {
                    "unhealthy": [
                        {
                            "namespace": "monitoring",
                            "name": "loki-0",
                            "phase": "Running",
                            "reason": "CrashLoopBackOff",
                            "node": "worker2",
                        }
                    ]
                },
            },
            "components": {
                "module": "components",
                "status": "warning",
                "message": "kube-proxy not ready on worker2",
            },
        },
    }


def run_fallback_e2e() -> None:
    """Validate fallback PR meta when Cursor is unavailable."""
    with Path(os.devnull).open("w") as devnull:
        old = os.environ.pop("CURSOR_API_KEY", None)
        try:
            meta = generate_pr_meta(_fault_injection_payload())
        finally:
            if old is not None:
                os.environ["CURSOR_API_KEY"] = old

    assert "title" in meta and meta["title"]
    assert "body" in meta
    assert "pods" in meta["title"] or "pods" in meta["body"]
    branch = meta.get("branch") or ""
    assert branch.startswith("sentinel/fix-"), branch
    assert sanitize_git_branch_slug("pods, components").startswith("sentinel/fix-")
    print("✓ fallback generate_pr_meta OK")
    print(json.dumps({k: meta[k] for k in ("title", "branch") if k in meta}, indent=2))


def run_cursor_e2e() -> None:
    """Optional live Cursor SDK call (requires CURSOR_API_KEY)."""
    if not os.getenv("CURSOR_API_KEY"):
        print("skip Cursor E2E: CURSOR_API_KEY not set", file=sys.stderr)
        return
    meta = generate_pr_meta(_fault_injection_payload())
    if not meta.get("files"):
        print("⚠ Cursor returned no files (acceptable for dry-run)", file=sys.stderr)
    print("✓ Cursor generate_pr_meta OK")
    print(json.dumps(meta, indent=2)[:2000])


def main() -> int:
    parser = argparse.ArgumentParser(description="GitOps fault-injection E2E")
    parser.add_argument(
        "--with-cursor",
        action="store_true",
        help="Also call Cursor SDK when CURSOR_API_KEY is set",
    )
    args = parser.parse_args()
    run_fallback_e2e()
    if args.with_cursor:
        run_cursor_e2e()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
