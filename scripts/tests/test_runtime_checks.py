"""Unit tests for containerd / kubelet checks."""

from __future__ import annotations

import unittest

from checks.containerd_check import ContainerdCheck
from checks.kubelet_check import KubeletCheck


def _node(
    name: str,
    *,
    ready: str = "True",
    reason: str = "KubeletReady",
    runtime: str = "containerd://1.7.28",
    cordoned: bool = False,
) -> dict:
    return {
        "metadata": {"name": name},
        "spec": {"unschedulable": cordoned},
        "status": {
            "conditions": [{"type": "Ready", "status": ready, "reason": reason}],
            "nodeInfo": {"containerRuntimeVersion": runtime},
        },
    }


class ContainerdCheckTests(unittest.TestCase):
    """ContainerdCheck node analysis."""

    def setUp(self) -> None:
        self.check = ContainerdCheck()

    def test_healthy_node(self) -> None:
        detail = self.check._analyze_node(_node("worker4"))
        self.assertFalse(detail["unhealthy"])

    def test_unknown_runtime(self) -> None:
        detail = self.check._analyze_node(
            _node("cp1", ready="False", reason="NodeStatusUnknown", runtime="containerd://Unknown")
        )
        self.assertTrue(detail["unhealthy"])
        self.assertIn("runtime=containerd://Unknown", detail["signals"])


class KubeletCheckTests(unittest.TestCase):
    """KubeletCheck node analysis."""

    def setUp(self) -> None:
        self.check = KubeletCheck()

    def test_not_ready_signals(self) -> None:
        signals = self.check._signals(False, "NodeStatusUnknown", True)
        self.assertIn("NotReady (NodeStatusUnknown)", signals)

    def test_cordoned_signal(self) -> None:
        signals = self.check._signals(True, "KubeletReady", False)
        self.assertIn("SchedulingDisabled (cordoned)", signals)


if __name__ == "__main__":
    unittest.main()
