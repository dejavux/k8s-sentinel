"""
K8s Sentinel - 失敗 CronJob / Job 診斷（alert-only）

收集 failed Job 與 log snippet，供 Telegram / agent 排查；不自動刪除或重跑。
"""

from __future__ import annotations

import json
import os
import subprocess
from json import JSONDecodeError
from typing import Any

from .base import BaseCheck, CheckResult, FixResult

LOG_TAIL = int(os.getenv("SENTINEL_CRONJOB_LOG_TAIL", "30"))
MAX_FAILED = int(os.getenv("SENTINEL_CRONJOB_MAX_FAILED", "10"))
NAMESPACE_CSV = os.getenv("SENTINEL_CRONJOB_NAMESPACES", "")

KNOWN_LOG_PATTERNS: tuple[tuple[str, str], ...] = (
    ("mapfile: not found", "Alpine /bin/sh 不支援 mapfile；CronJob 需 bash 或改 while read"),
    ("BackoffLimitExceeded", "Job 達 backoff 上限；查 kubectl logs job/<name> --previous"),
    ("204 No Content", "Prometheus scrape /_health 回 204 會 up=0；移除 prometheus.io/scrape"),
    ("404 Not Found", "Prometheus scrape /metrics 不存在；勿對非 exporter 加 scrape annotation"),
    ("connection refused", "Pod 未監聽或網路問題；查 describe pod / endpoints"),
)


def _kubectl_json(args: list[str]) -> dict[str, Any]:
    proc = subprocess.run(
        ["kubectl", *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return json.loads(proc.stdout)


def _namespace_allowed(namespace: str, allowed: set[str] | None) -> bool:
    if not allowed:
        return True
    return namespace in allowed


def _parse_allowed_namespaces() -> set[str] | None:
    if not NAMESPACE_CSV.strip():
        return None
    parts = {part.strip() for part in NAMESPACE_CSV.split(",") if part.strip()}
    return parts or None


def _match_known_patterns(text: str) -> list[str]:
    hints: list[str] = []
    lowered = text.lower()
    for needle, hint in KNOWN_LOG_PATTERNS:
        if needle.lower() in lowered and hint not in hints:
            hints.append(hint)
    return hints


def _fetch_job_logs(namespace: str, job_name: str) -> str:
    label_selector = f"job-name={job_name}"
    for previous in (False, True):
        cmd = [
            "kubectl",
            "logs",
            "-n",
            namespace,
            "-l",
            label_selector,
            f"--tail={LOG_TAIL}",
            "--all-containers",
        ]
        if previous:
            cmd.append("--previous")
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=45,
            )
        except subprocess.TimeoutExpired:
            return "[log fetch timeout]"
        if proc.stdout.strip():
            return proc.stdout.strip()[-4000:]
        if proc.stderr.strip() and "NotFound" not in proc.stderr:
            return proc.stderr.strip()[-1000:]
    return "[no logs available]"


class CronJobsCheck(BaseCheck):
    """Failed batch Job diagnostic check (alert-only)."""

    @property
    def name(self) -> str:
        return "cronjobs"

    @property
    def description(self) -> str:
        return "掃描 failed Job（含 CronJob 觸發）並附 log snippet 供排查"

    def check(self) -> CheckResult:
        self.logger.info("Starting %s check...", self.name)
        allowed = _parse_allowed_namespaces()

        try:
            data = _kubectl_json(["get", "jobs", "-A", "-o", "json"])
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, JSONDecodeError) as exc:
            return CheckResult(
                module=self.name,
                status="error",
                message=f"Failed to list jobs: {exc}",
            )

        failed_jobs: list[dict[str, Any]] = []
        for item in data.get("items") or []:
            meta = item.get("metadata") or {}
            status = item.get("status") or {}
            namespace = meta.get("namespace") or ""
            name = meta.get("name") or ""
            if not namespace or not name:
                continue
            if not _namespace_allowed(namespace, allowed):
                continue
            failed_count = int(status.get("failed") or 0)
            active = int(status.get("active") or 0)
            if failed_count < 1 or active > 0:
                continue

            log_snippet = _fetch_job_logs(namespace, name)
            hints = _match_known_patterns(log_snippet)
            owner_refs = meta.get("ownerReferences") or []
            cronjob = next(
                (ref.get("name") for ref in owner_refs if ref.get("kind") == "CronJob"),
                None,
            )
            failed_jobs.append(
                {
                    "namespace": namespace,
                    "job": name,
                    "cronjob": cronjob,
                    "failed_pods": failed_count,
                    "log_snippet": log_snippet,
                    "known_patterns": hints,
                }
            )

        failed_jobs.sort(key=lambda row: (row["namespace"], row["job"]))
        if len(failed_jobs) > MAX_FAILED:
            failed_jobs = failed_jobs[:MAX_FAILED]

        details: dict[str, Any] = {
            "max_listed": MAX_FAILED,
            "log_tail": LOG_TAIL,
            "failed_jobs": failed_jobs,
        }
        if allowed:
            details["namespaces"] = sorted(allowed)

        if not failed_jobs:
            return CheckResult(
                module=self.name,
                status="ok",
                message="No failed batch jobs found",
                details=details,
            )

        with_hints = sum(1 for row in failed_jobs if row.get("known_patterns"))
        return CheckResult(
            module=self.name,
            status="warning",
            message=(
                f"Found {len(failed_jobs)} failed job(s)"
                + (f"; {with_hints} matched known patterns" if with_hints else "")
            ),
            details=details,
            affected_nodes=sorted({row["namespace"] for row in failed_jobs}),
        )

    def can_auto_fix(self) -> bool:
        return False

    def fix(self, check_result: CheckResult) -> FixResult:
        return FixResult(
            module=self.name,
            success=True,
            message="Alert-only module; inspect failed_jobs log_snippet in details",
            fixed_nodes=[],
            failed_nodes=check_result.affected_nodes or [],
            details={"skipped": True},
        )
