"""
K8s Sentinel - 失敗 CronJob / Job 診斷（alert-only）

收集近期 failed Job 與 log snippet；可選自動清理過期 failed Job 物件。
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from json import JSONDecodeError
from typing import Any

from .base import BaseCheck, CheckResult, FixResult

LOG_TAIL = int(os.getenv("SENTINEL_CRONJOB_LOG_TAIL", "30"))
MAX_FAILED = int(os.getenv("SENTINEL_CRONJOB_MAX_FAILED", "10"))
MAX_AGE_HOURS = int(os.getenv("SENTINEL_CRONJOB_MAX_AGE_HOURS", "48"))
STALE_HOURS = int(os.getenv("SENTINEL_CRONJOB_STALE_HOURS", str(MAX_AGE_HOURS)))
NAMESPACE_CSV = os.getenv("SENTINEL_CRONJOB_NAMESPACES", "")
SKIP_JOB_PREFIXES = tuple(
    part.strip()
    for part in os.getenv(
        "SENTINEL_CRONJOB_SKIP_JOB_PREFIXES",
        "k8s-sentinel-",
    ).split(",")
    if part.strip()
)

KNOWN_LOG_PATTERNS: tuple[tuple[str, str], ...] = (
    ("mapfile: not found", "Alpine /bin/sh 不支援 mapfile；CronJob 需 bash 或改 while read"),
    ("BackoffLimitExceeded", "Job 達 backoff 上限；查 kubectl logs job/<name> --previous"),
    ("204 No Content", "Prometheus scrape /_health 回 204 會 up=0；移除 prometheus.io/scrape"),
    ("404 Not Found", "Prometheus scrape /metrics 不存在；勿對非 exporter 加 scrape annotation"),
    ("connection refused", "Pod 未監聽或網路問題；查 describe pod / endpoints"),
)


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _job_failed_at(item: dict[str, Any]) -> datetime | None:
    status = item.get("status") or {}
    failed_at = _parse_ts(status.get("completionTime"))
    if failed_at is not None:
        return failed_at
    for cond in status.get("conditions") or []:
        if cond.get("type") == "Failed":
            failed_at = _parse_ts(cond.get("lastTransitionTime"))
            if failed_at is not None:
                return failed_at
    return _parse_ts((item.get("metadata") or {}).get("creationTimestamp"))


def _should_skip_job(name: str) -> bool:
    return any(name.startswith(prefix) for prefix in SKIP_JOB_PREFIXES)


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


def _is_failed_job(item: dict[str, Any]) -> bool:
    status = item.get("status") or {}
    failed_count = int(status.get("failed") or 0)
    active = int(status.get("active") or 0)
    return failed_count >= 1 and active == 0


def _summarize_jobs(failed_jobs: list[dict[str, Any]], total_recent: int) -> str:
    if not failed_jobs:
        return "No recent failed batch jobs found"
    labels = [
        f"{row['namespace']}/{row['job']}"
        for row in failed_jobs[:3]
    ]
    suffix = ", ".join(labels)
    extra = total_recent - len(labels)
    if extra > 0:
        suffix = f"{suffix} (+{extra} more)"
    return f"Found {total_recent} recent failed job(s): {suffix}"


class CronJobsCheck(BaseCheck):
    """Failed batch Job diagnostic check (alert-only for recent failures)."""

    @property
    def name(self) -> str:
        return "cronjobs"

    @property
    def description(self) -> str:
        return "掃描近期 failed Job（含 CronJob 觸發）並附 log snippet 供排查"

    def _collect_failed_jobs(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        allowed = _parse_allowed_namespaces()
        data = _kubectl_json(["get", "jobs", "-A", "-o", "json"])
        now = datetime.now(timezone.utc)
        recent_cutoff = now - timedelta(hours=MAX_AGE_HOURS)

        failed_jobs: list[dict[str, Any]] = []
        stale_jobs: list[dict[str, str]] = []

        for item in data.get("items") or []:
            meta = item.get("metadata") or {}
            namespace = meta.get("namespace") or ""
            name = meta.get("name") or ""
            if not namespace or not name or not _is_failed_job(item):
                continue
            if not _namespace_allowed(namespace, allowed):
                continue
            if _should_skip_job(name):
                continue

            failed_at = _job_failed_at(item)
            if failed_at is None:
                continue
            if failed_at < recent_cutoff:
                stale_jobs.append({"namespace": namespace, "job": name})
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
                    "failed_at": failed_at.isoformat(),
                    "failed_pods": int((item.get("status") or {}).get("failed") or 0),
                    "log_snippet": log_snippet,
                    "known_patterns": hints,
                }
            )

        failed_jobs.sort(key=lambda row: row["failed_at"], reverse=True)
        total_recent = len(failed_jobs)
        if total_recent > MAX_FAILED:
            failed_jobs = failed_jobs[:MAX_FAILED]

        details: dict[str, Any] = {
            "max_listed": MAX_FAILED,
            "max_age_hours": MAX_AGE_HOURS,
            "stale_hours": STALE_HOURS,
            "log_tail": LOG_TAIL,
            "failed_jobs": failed_jobs,
            "recent_failed_total": total_recent,
            "stale_failed_total": len(stale_jobs),
            "stale_jobs": stale_jobs[:50],
        }
        if allowed:
            details["namespaces"] = sorted(allowed)
        return failed_jobs, details

    def check(self) -> CheckResult:
        self.logger.info("Starting %s check...", self.name)
        try:
            failed_jobs, details = self._collect_failed_jobs()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, JSONDecodeError) as exc:
            return CheckResult(
                module=self.name,
                status="error",
                message=f"Failed to list jobs: {exc}",
            )

        total_recent = int(details.get("recent_failed_total") or 0)
        if not failed_jobs:
            stale_total = int(details.get("stale_failed_total") or 0)
            msg = "No recent failed batch jobs found"
            if stale_total:
                msg = f"{msg} ({stale_total} stale failed job(s) older than {STALE_HOURS}h ignored)"
            return CheckResult(
                module=self.name,
                status="ok",
                message=msg,
                details=details,
            )

        with_hints = sum(1 for row in failed_jobs if row.get("known_patterns"))
        message = _summarize_jobs(failed_jobs, total_recent)
        if with_hints:
            message = f"{message}; {with_hints} matched known patterns"
        return CheckResult(
            module=self.name,
            status="warning",
            message=message,
            details=details,
            affected_nodes=sorted({row["namespace"] for row in failed_jobs}),
        )

    def can_auto_fix(self) -> bool:
        return os.getenv("SENTINEL_CRONJOB_CLEANUP_STALE", "true").lower() == "true"

    def fix(self, check_result: CheckResult) -> FixResult:
        stale_jobs = (check_result.details or {}).get("stale_jobs") or []
        if not stale_jobs:
            return FixResult(
                module=self.name,
                success=True,
                message="No stale failed jobs to delete",
                fixed_nodes=[],
                failed_nodes=[],
                details={"deleted": 0},
            )

        deleted: list[str] = []
        errors: list[str] = []
        for row in stale_jobs:
            namespace = row.get("namespace") or ""
            name = row.get("job") or ""
            if not namespace or not name:
                continue
            proc = subprocess.run(
                ["kubectl", "delete", "job", name, "-n", namespace, "--ignore-not-found"],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            label = f"{namespace}/{name}"
            if proc.returncode == 0:
                deleted.append(label)
                self.logger.info("Deleted stale failed job %s", label)
            else:
                err = (proc.stderr or proc.stdout or "delete failed").strip()
                errors.append(f"{label}: {err}")

        return FixResult(
            module=self.name,
            success=not errors,
            message=f"Deleted {len(deleted)} stale failed job(s)",
            fixed_nodes=deleted,
            failed_nodes=errors,
            details={"deleted": len(deleted), "errors": errors},
        )
