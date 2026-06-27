"""Unit tests for cronjobs check."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from checks.base import CheckResult
from checks.cronjobs_check import (
    CronJobsCheck,
    _job_failed_at,
    _match_known_patterns,
    _namespace_allowed,
    _should_skip_job,
)


def _job_item(
    namespace: str,
    name: str,
    *,
    failed_at: datetime,
    cronjob: str | None = "demo-cleanup",
) -> dict:
    owner_refs = []
    if cronjob:
        owner_refs.append({"kind": "CronJob", "name": cronjob})
    ts = failed_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "metadata": {
            "name": name,
            "namespace": namespace,
            "creationTimestamp": ts,
            "ownerReferences": owner_refs,
        },
        "status": {
            "failed": 1,
            "active": 0,
            "completionTime": ts,
            "conditions": [
                {
                    "type": "Failed",
                    "status": "True",
                    "lastTransitionTime": ts,
                }
            ],
        },
    }


class CronJobsCheckTests(unittest.TestCase):
    """CronJobsCheck failed job detection."""

    def test_match_known_patterns_mapfile(self) -> None:
        hints = _match_known_patterns("/bin/sh: mapfile: not found")
        self.assertTrue(any("mapfile" in hint for hint in hints))

    def test_namespace_allowed_filter(self) -> None:
        allowed = {"grid-bot-shared-services", "fuqi-asset-manager"}
        self.assertTrue(_namespace_allowed("grid-bot-shared-services", allowed))
        self.assertFalse(_namespace_allowed("default", allowed))

    def test_skip_sentinel_manual_jobs(self) -> None:
        self.assertTrue(_should_skip_job("k8s-sentinel-verify-123"))

    def test_job_failed_at_uses_completion_time(self) -> None:
        item = _job_item("ns", "job", failed_at=datetime(2026, 6, 27, tzinfo=timezone.utc))
        self.assertEqual(_job_failed_at(item).year, 2026)

    def test_recent_failed_job_warning(self) -> None:
        recent = datetime.now(timezone.utc) - timedelta(hours=2)
        jobs_payload = {"items": [_job_item("grid-bot-shared-services", "demo-cleanup-123", failed_at=recent)]}
        check = CronJobsCheck()
        with patch("checks.cronjobs_check._kubectl_json", return_value=jobs_payload):
            with patch(
                "checks.cronjobs_check._fetch_job_logs",
                return_value="mapfile: not found",
            ):
                result = check.check()
        self.assertEqual(result.status, "warning")
        self.assertIn("demo-cleanup-123", result.message)
        self.assertEqual(len(result.details["failed_jobs"]), 1)

    def test_old_failed_jobs_ignored(self) -> None:
        old = datetime.now(timezone.utc) - timedelta(days=30)
        jobs_payload = {"items": [_job_item("default", "old-job", failed_at=old)]}
        check = CronJobsCheck()
        with patch("checks.cronjobs_check._kubectl_json", return_value=jobs_payload):
            result = check.check()
        self.assertEqual(result.status, "ok")
        self.assertIn("No recent failed", result.message)

    def test_stale_jobs_deleted_on_fix(self) -> None:
        check = CronJobsCheck()
        check_result = CheckResult(
            module="cronjobs",
            status="ok",
            message="ok",
            details={"stale_jobs": [{"namespace": "default", "job": "old-job"}]},
        )
        with patch("checks.cronjobs_check.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "deleted"
            mock_run.return_value.stderr = ""
            fix = check.fix(check_result)
        self.assertTrue(fix.success)
        self.assertEqual(fix.details["deleted"], 1)


if __name__ == "__main__":
    unittest.main()
