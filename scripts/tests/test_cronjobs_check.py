"""Unit tests for cronjobs check."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from checks.cronjobs_check import (
    CronJobsCheck,
    _match_known_patterns,
    _namespace_allowed,
)


class CronJobsCheckTests(unittest.TestCase):
    """CronJobsCheck failed job detection."""

    def test_match_known_patterns_mapfile(self) -> None:
        hints = _match_known_patterns("/bin/sh: mapfile: not found")
        self.assertTrue(any("mapfile" in hint for hint in hints))

    def test_namespace_allowed_filter(self) -> None:
        allowed = {"grid-bot-shared-services", "fuqi-asset-manager"}
        self.assertTrue(_namespace_allowed("grid-bot-shared-services", allowed))
        self.assertFalse(_namespace_allowed("default", allowed))

    def test_failed_job_warning(self) -> None:
        jobs_payload = {
            "items": [
                {
                    "metadata": {
                        "name": "demo-cleanup-123",
                        "namespace": "grid-bot-shared-services",
                        "ownerReferences": [
                            {"kind": "CronJob", "name": "demo-cleanup"},
                        ],
                    },
                    "status": {"failed": 1, "active": 0},
                }
            ]
        }
        check = CronJobsCheck()
        with patch("checks.cronjobs_check._kubectl_json", return_value=jobs_payload):
            with patch(
                "checks.cronjobs_check._fetch_job_logs",
                return_value="mapfile: not found",
            ):
                result = check.check()
        self.assertEqual(result.status, "warning")
        self.assertEqual(len(result.details["failed_jobs"]), 1)
        self.assertTrue(result.details["failed_jobs"][0]["known_patterns"])

    def test_no_failed_jobs_ok(self) -> None:
        check = CronJobsCheck()
        with patch("checks.cronjobs_check._kubectl_json", return_value={"items": []}):
            result = check.check()
        self.assertEqual(result.status, "ok")


if __name__ == "__main__":
    unittest.main()
