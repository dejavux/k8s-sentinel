"""Unit tests for PodCheck stale bare-sidecar detection."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from checks.pod_check import PodCheck


def _bare_pod(
    *,
    completed_name: str = "smoke",
    sidecar_name: str = "gluetun",
    completed_exit: int = 0,
    sidecar_running: bool = True,
) -> dict:
    containers = [
        {"name": completed_name},
        {"name": sidecar_name},
    ]
    statuses = [
        {
            "name": completed_name,
            "ready": False,
            "state": {
                "terminated": {
                    "exitCode": completed_exit,
                    "reason": "Completed",
                    "finishedAt": "2026-07-18T07:00:00Z",
                }
            },
        },
        {
            "name": sidecar_name,
            "ready": False,
            "state": (
                {"running": {"startedAt": "2026-07-18T06:56:00Z"}}
                if sidecar_running
                else {"terminated": {"exitCode": 0, "reason": "Completed"}}
            ),
        },
    ]
    return {
        "metadata": {
            "namespace": "fuqi-asset-manager",
            "name": "polymarket-sdk-smoke-fuqi",
            "creationTimestamp": "2026-07-17T13:00:00Z",
            "ownerReferences": [],
        },
        "spec": {"containers": containers, "nodeName": "worker5"},
        "status": {
            "phase": "Running",
            "conditions": [{"type": "Ready", "status": "False"}],
            "containerStatuses": statuses,
        },
    }


class StaleBareSidecarTests(unittest.TestCase):
    def test_detects_completed_workload_plus_running_gluetun(self) -> None:
        self.assertTrue(PodCheck._is_stale_bare_sidecar_pod(_bare_pod()))

    def test_ignores_owned_pods(self) -> None:
        pod = _bare_pod()
        pod["metadata"]["ownerReferences"] = [
            {"kind": "ReplicaSet", "name": "rs-1", "controller": True}
        ]
        self.assertFalse(PodCheck._is_stale_bare_sidecar_pod(pod))

    def test_ignores_single_container(self) -> None:
        pod = _bare_pod()
        pod["spec"]["containers"] = [{"name": "only"}]
        pod["status"]["containerStatuses"] = pod["status"]["containerStatuses"][:1]
        self.assertFalse(PodCheck._is_stale_bare_sidecar_pod(pod))

    def test_analyze_marks_auto_fixable_without_gitops(self) -> None:
        check = PodCheck()
        pod = _bare_pod()
        with (
            patch.object(check, "_pod_logs", return_value=""),
            patch.object(check, "_pod_events", return_value=[]),
            patch.object(check, "_unready_age_seconds", return_value=3600),
        ):
            issue = check._analyze_pod(pod)
        self.assertIsNotNone(issue)
        assert issue is not None
        self.assertEqual(issue["problem"], "NotReady")
        self.assertTrue(issue["auto_fixable"])
        self.assertFalse(issue["needs_gitops"])
        self.assertTrue(issue["stale_bare_sidecar"])

    def test_fix_deletes_stale_bare_sidecar(self) -> None:
        check = PodCheck()
        issue = {
            "namespace": "fuqi-asset-manager",
            "name": "polymarket-sdk-smoke-fuqi",
            "problem": "NotReady",
            "auto_fixable": True,
            "stale_bare_sidecar": True,
            "needs_gitops": False,
        }
        result = MagicMock()
        result.is_healthy.return_value = False
        result.details = {"issues": [issue]}
        with patch.object(check, "_restart_pod", return_value=True) as restart:
            fix = check.fix(result)
        restart.assert_called_once_with(
            "fuqi-asset-manager", "polymarket-sdk-smoke-fuqi"
        )
        self.assertTrue(fix.success)
        self.assertEqual(fix.fixed_nodes, ["fuqi-asset-manager/polymarket-sdk-smoke-fuqi"])
        self.assertEqual(fix.details["actions"][0]["action"], "deleted_stale_bare_sidecar")


if __name__ == "__main__":
    unittest.main()
