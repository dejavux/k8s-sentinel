"""Unit tests for PodCheck pending diagnostics."""

from __future__ import annotations

import unittest

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

    def test_is_disk_eviction_diskpressure_brackets(self) -> None:
        message = "Pod was rejected: The node had condition: [DiskPressure]. "
        self.assertTrue(PodCheck._is_disk_eviction(message))


if __name__ == "__main__":
    unittest.main()
