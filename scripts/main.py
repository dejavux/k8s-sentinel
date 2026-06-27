#!/usr/bin/env python3
"""
K8s Sentinel - 主程序

自動化 Kubernetes 叢集健康檢查與修復
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import urllib.error
from datetime import datetime
from typing import Any, Dict, List, Optional

from checks import CheckRegistry
from checks.components_check import ComponentsCheck
from checks.containerd_check import ContainerdCheck
from checks.cronjobs_check import CronJobsCheck
from checks.disk_check import DiskCheck
from checks.kubelet_check import KubeletCheck
from checks.pod_check import PodCheck
from checks.resources_check import ResourcesCheck
from checks.runc_check import RuncCheck
from gitops.eligibility import should_create_fix_pr
from gitops.pr_creator import create_fix_pr
from gitops.repo_bootstrap import ensure_clone
from notify.telegram import maybe_send_telegram_summary
from metrics.prometheus import render_prometheus_metrics
from metrics.pushgateway import push_prometheus_metrics

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def register_checks() -> None:
    """註冊所有檢查模組"""
    CheckRegistry.register(RuncCheck())
    CheckRegistry.register(DiskCheck())
    CheckRegistry.register(PodCheck())
    CheckRegistry.register(ComponentsCheck())
    CheckRegistry.register(ContainerdCheck())
    CheckRegistry.register(KubeletCheck())
    CheckRegistry.register(ResourcesCheck())
    CheckRegistry.register(CronJobsCheck())

    logger.info("Registered %d check modules", len(CheckRegistry.list_all()))


def normalize_modules(modules: Optional[List[str]]) -> List[str]:
    """Expand comma-separated module names (e.g. runc,disk)."""
    if modules is None:
        env = os.getenv("SENTINEL_MODULES", "all")
        modules = [m.strip() for m in env.split(",") if m.strip()]
    expanded: List[str] = []
    for name in modules:
        for part in name.split(","):
            part = part.strip()
            if part:
                expanded.append(part)
    return expanded or ["all"]


def run_checks(modules: Optional[List[str]] = None) -> Dict[str, Any]:
    """執行檢查"""
    modules = normalize_modules(modules)
    if "all" in modules:
        modules = CheckRegistry.list_all()

    logger.info("Running checks: %s", ", ".join(modules))

    results: Dict[str, Any] = {}
    for module_name in modules:
        check = CheckRegistry.get(module_name)
        if check is None:
            logger.warning("Module not found: %s", module_name)
            continue

        logger.info("Checking %s...", module_name)
        result = check.check()
        results[module_name] = result

        if result.is_healthy():
            logger.info("✓ %s: %s", module_name, result.message)
        else:
            logger.warning("✗ %s: %s", module_name, result.message)

    return results


def run_fixes(
    check_results: Dict[str, Any], modules: Optional[List[str]] = None
) -> Dict[str, Any]:
    """執行修復"""
    modules = normalize_modules(modules)
    if "all" in modules:
        modules = list(check_results.keys())

    logger.info("Running fixes: %s", ", ".join(modules))

    fix_results: Dict[str, Any] = {}
    for module_name in modules:
        if module_name not in check_results:
            logger.warning("No check result for module: %s", module_name)
            continue

        check_result = check_results[module_name]
        if check_result.is_healthy():
            logger.info("Skipping %s: already healthy", module_name)
            continue

        check = CheckRegistry.get(module_name)
        if check is None or not check.can_auto_fix():
            logger.warning("Module %s cannot auto-fix", module_name)
            continue

        logger.info("Fixing %s...", module_name)
        fix_result = check.fix(check_result)
        fix_results[module_name] = fix_result

        if fix_result.success:
            logger.info("✓ %s: %s", module_name, fix_result.message)
        else:
            logger.error("✗ %s: %s", module_name, fix_result.message)

    return fix_results


def maybe_create_fix_pr(
    check_results: Dict[str, Any], fix_results: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Phase 4: Cursor SDK + gh PR when SENTINEL_AUTO_PR=true."""
    if not should_create_fix_pr(check_results, fix_results):
        logger.info("Skipping auto PR (no GitOps-worthy issues)")
        return None

    try:
        ensure_clone()
    except (subprocess.CalledProcessError, OSError, RuntimeError) as exc:
        logger.exception("Repo bootstrap failed: %s", exc)
        return {"success": False, "message": str(exc)}

    payload = {
        "timestamp": datetime.utcnow().isoformat(),
        "checks": {k: v.to_dict() for k, v in check_results.items()},
        "fixes": {k: v.to_dict() for k, v in fix_results.items()},
    }
    auto_merge = os.getenv("SENTINEL_AUTO_MERGE", "false").lower() == "true"
    try:
        result = create_fix_pr(payload, auto_merge=auto_merge)
    except (subprocess.CalledProcessError, OSError, json.JSONDecodeError) as exc:
        logger.exception("Auto PR failed: %s", exc)
        return {"success": False, "message": str(exc)}
    if result.get("success"):
        logger.info("PR created: %s", result.get("pr_url"))
        if result.get("merged"):
            logger.info("PR auto-merged: %s", result.get("pr_url"))
        elif result.get("auto_merge_skipped"):
            logger.info("Auto-merge skipped: %s", result.get("auto_merge_skipped"))
    else:
        logger.warning("PR not created: %s", result.get("message"))
    return result


def save_results(
    check_results: Dict[str, Any], fix_results: Optional[Dict[str, Any]] = None
) -> None:
    """儲存結果"""
    output = {
        "timestamp": datetime.utcnow().isoformat(),
        "checks": {k: v.to_dict() for k, v in check_results.items()},
    }

    if fix_results:
        output["fixes"] = {k: v.to_dict() for k, v in fix_results.items()}

    print("\n" + "=" * 60)
    print("SENTINEL RESULTS")
    print("=" * 60)
    print(json.dumps(output, indent=2))
    print("=" * 60)

    output_file = os.getenv("SENTINEL_OUTPUT_FILE")
    if output_file:
        with open(output_file, "w", encoding="utf-8") as handle:
            json.dump(output, handle, indent=2)

    metrics_file = os.getenv("SENTINEL_METRICS_FILE")
    metrics_text = ""
    if metrics_file or os.getenv("SENTINEL_PUSHGATEWAY_URL"):
        metrics_text = render_prometheus_metrics(check_results)
    if metrics_file:
        with open(metrics_file, "w", encoding="utf-8") as handle:
            handle.write(metrics_text)
        logger.info("Metrics written to: %s", metrics_file)

    pushgateway_url = os.getenv("SENTINEL_PUSHGATEWAY_URL")
    if pushgateway_url and metrics_text:
        job = os.getenv("SENTINEL_PUSHGATEWAY_JOB", "k8s-sentinel")
        try:
            push_prometheus_metrics(pushgateway_url, job, metrics_text)
            logger.info("Metrics pushed to Pushgateway job=%s", job)
        except urllib.error.URLError:
            logger.warning("Continuing without Pushgateway (check still succeeded)")


def main() -> int:
    """主程序"""
    parser = argparse.ArgumentParser(
        description="K8s Sentinel - 自動化叢集健康檢查與修復"
    )
    parser.add_argument("command", choices=["check", "fix", "list"], help="執行命令")
    parser.add_argument(
        "--modules", nargs="+", default=["all"], help="要執行的模組（預設: all）"
    )
    parser.add_argument("--auto-fix", action="store_true", help="檢查後自動修復")

    args = parser.parse_args()
    register_checks()

    if args.command == "list":
        print("Available modules:")
        for module_name in CheckRegistry.list_all():
            check = CheckRegistry.get(module_name)
            if check:
                print(f"  - {module_name}: {check.description}")
        return 0

    if args.command == "check":
        check_results = run_checks(args.modules)
        fix_results = None
        pr_result: Optional[Dict[str, Any]] = None

        if args.auto_fix or os.getenv("SENTINEL_AUTO_FIX", "false").lower() == "true":
            disk_check = CheckRegistry.get("disk")
            if isinstance(disk_check, DiskCheck):
                pruned = disk_check.prune_stale_pods()
                logger.info("Pruned %d stale pod(s) cluster-wide", pruned)
            fix_results = run_fixes(check_results, args.modules)
            if fix_results:
                pr_result = maybe_create_fix_pr(check_results, fix_results)
            logger.info("Re-running checks after auto-fix...")
            check_results = run_checks(args.modules)
            if any(r.status == "error" for r in check_results.values()):
                logger.info("Post-fix errors remain; running second fix pass...")
                extra = run_fixes(check_results, args.modules)
                if extra:
                    fix_results = {**(fix_results or {}), **extra}
                check_results = run_checks(args.modules)

        save_results(check_results, fix_results)
        maybe_send_telegram_summary(
            check_results, fix_results, pr_result=pr_result
        )
        has_errors = any(r.status == "error" for r in check_results.values())
        disk = check_results.get("disk")
        fail_on_disk_warn = (
            os.getenv("SENTINEL_DISK_WARN_FAIL", "true").lower() == "true"
        )
        has_disk_warn = disk is not None and disk.status == "warning"
        return 1 if has_errors or (fail_on_disk_warn and has_disk_warn) else 0

    if args.command == "fix":
        check_results = run_checks(args.modules)
        fix_results = run_fixes(check_results, args.modules)
        pr_result = None
        if fix_results:
            pr_result = maybe_create_fix_pr(check_results, fix_results)
        save_results(check_results, fix_results)
        maybe_send_telegram_summary(
            check_results, fix_results, pr_result=pr_result
        )

        has_failures = any(not r.success for r in fix_results.values())
        return 1 if has_failures else 0

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(130)
