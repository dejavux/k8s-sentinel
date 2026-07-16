"""Unit tests for PodCheck pending diagnostics."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from checks.pod_check import PodCheck


def _pending_pod(
    *,
    scheduling_message: str = "",
    scheduling_reason: str = "Unschedulable",
    node_selector: dict[str, str] | None = None,
    requests: dict[str, str] | None = None,
    pvc_claims: list[str] | None = None,
) -> dict:
    containers: list[dict] = [{"name": "main"}]
    if requests:
        containers[0]["resources"] = {"requests": requests}

    volumes = []
    if pvc_claims:
        for claim in pvc_claims:
            volumes.append({"persistentVolumeClaim": {"claimName": claim}})

    pod: dict = {
        "metadata": {"name": "vpn-verify", "namespace": "vpn-egress"},
        "spec": {"containers": containers, "volumes": volumes},
        "status": {
            "phase": "Pending",
            "conditions": [
                {
                    "type": "PodScheduled",
                    "status": "False",
                    "reason": scheduling_reason,
                    "message": scheduling_message,
                }
            ],
        },
    }
    if node_selector:
        pod["spec"]["nodeSelector"] = node_selector
    return pod


class PodCheckPendingDiagnosticsTests(unittest.TestCase):
    """PodCheck._pending_diagnostics and _classify_pending."""

    def setUp(self) -> None:
        self.check = PodCheck()

    def test_classify_node_affinity(self) -> None:
        events = [
            "FailedScheduling: 0/3 nodes are available: 3 node(s) didn't match "
            "pod's node affinity/selector."
        ]
        category = PodCheck._classify_pending({}, events)
        self.assertEqual(category, "node_affinity")

    def test_classify_insufficient_memory(self) -> None:
        diag = {
            "scheduling_message": "0/3 nodes are available: 3 Insufficient memory.",
        }
        category = PodCheck._classify_pending(diag, [])
        self.assertEqual(category, "insufficient_memory")

    def test_classify_disk_pressure(self) -> None:
        events = ["FailedScheduling: node has disk-pressure taint"]
        category = PodCheck._classify_pending({}, events)
        self.assertEqual(category, "disk_pressure")

    def test_pending_diagnostics_collects_spec_and_status(self) -> None:
        pod = _pending_pod(
            scheduling_message="0/2 nodes didn't match pod's node affinity/selector.",
            node_selector={"vpn-egress": "true"},
            requests={"cpu": "100m", "memory": "128Mi"},
            pvc_claims=["vpn-data"],
        )
        diag = self.check._pending_diagnostics(
            pod,
            ["FailedScheduling: didn't match pod's node affinity/selector."],
        )
        self.assertEqual(diag["pending_category"], "node_affinity")
        self.assertEqual(diag["node_selector"], {"vpn-egress": "true"})
        self.assertEqual(diag["resource_requests"], {"cpu": "100m", "memory": "128Mi"})
        self.assertEqual(diag["pvc_claims"], ["vpn-data"])
        self.assertIn("affinity", diag["scheduling_message"])


class PodCheckPendingFixTests(unittest.TestCase):
    """PodCheck._try_fix_pending remediation paths."""

    def setUp(self) -> None:
        self.check = PodCheck()

    @patch.object(PodCheck, "_apply_missing_node_labels")
    @patch.object(PodCheck, "_restart_pod", return_value=True)
    def test_node_affinity_labels_node_and_restarts(
        self, _mock_restart: MagicMock, mock_label: MagicMock
    ) -> None:
        def _label(issue: dict) -> bool:
            issue["labeled_node"] = "worker-1"
            return True

        mock_label.side_effect = _label
        issue = {
            "namespace": "vpn-egress",
            "name": "vpn-verify",
            "pending_category": "node_affinity",
            "node_selector": {"vpn-egress": "true"},
        }
        result = self.check._try_fix_pending(issue)
        self.assertEqual(
            result, ("labeled_node_and_restarted", {"labeled_node": "worker-1"})
        )

    @patch.object(PodCheck, "_rollout_restart_deployment", return_value=True)
    def test_deployment_pending_rollout_restart(
        self, _mock_rollout: MagicMock
    ) -> None:
        issue = {
            "namespace": "vpn-egress",
            "name": "vpn-verify-abc",
            "pending_category": "unknown",
            "owner_kind": "Deployment",
            "owner_name": "vpn-verify",
        }
        result = self.check._try_fix_pending(issue)
        self.assertEqual(result, ("rollout_restart", {}))

    @patch.object(PodCheck, "_restart_pod", return_value=True)
    def test_disk_pressure_restarts_pod(self, _mock_restart: MagicMock) -> None:
        issue = {
            "namespace": "vpn-egress",
            "name": "vpn-verify",
            "pending_category": "disk_pressure",
        }
        result = self.check._try_fix_pending(issue)
        self.assertEqual(result, ("restarted_after_disk_pressure", {}))


if __name__ == "__main__":
    unittest.main()
