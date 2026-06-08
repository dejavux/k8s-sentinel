"""Unit tests for k8s-sentinel disk checks."""

from __future__ import annotations

import unittest

from checks.disk_check import (
    DiskCheck,
    DEFAULT_DISK_ERROR_PERCENT,
    DEFAULT_DISK_WARN_PERCENT,
)
from fixers.ansible_runner import _parse_ansible_shell_line


class DiskCheckAnalyzeTests(unittest.TestCase):
    """Tests for DiskCheck.analyze_node threshold logic."""

    def setUp(self) -> None:
        self.check = DiskCheck()

    def test_analyze_node_disk_pressure(self) -> None:
        """DiskPressure condition should flag disk_pressure regardless of host stats."""
        node = {
            "metadata": {"name": "worker4", "labels": {}},
            "status": {
                "conditions": [{"type": "DiskPressure", "status": "True"}],
            },
        }
        detail = self.check.analyze_node(node, {"root_use_percent": 79.0})
        self.assertTrue(detail["disk_pressure"])
        self.assertFalse(detail["host_disk_warn"])

    def test_analyze_node_host_warn_threshold(self) -> None:
        """Host rootfs above warn threshold should set host_disk_warn."""
        node = {
            "metadata": {"name": "worker4", "labels": {}},
            "status": {"conditions": [{"type": "DiskPressure", "status": "False"}]},
        }
        detail = self.check.analyze_node(
            node,
            {
                "root_use_percent": float(DEFAULT_DISK_WARN_PERCENT + 1),
                "root_size": "46G",
                "root_used": "35G",
                "root_avail": "9.4G",
            },
        )
        self.assertTrue(detail["host_disk_warn"])
        self.assertFalse(detail["host_disk_error"])

    def test_analyze_node_host_error_threshold(self) -> None:
        """Host rootfs at or above error threshold should set host_disk_error."""
        node = {
            "metadata": {"name": "worker4", "labels": {}},
            "status": {"conditions": [{"type": "DiskPressure", "status": "False"}]},
        }
        detail = self.check.analyze_node(
            node, {"root_use_percent": float(DEFAULT_DISK_ERROR_PERCENT)}
        )
        self.assertTrue(detail["host_disk_error"])
        self.assertFalse(detail["host_disk_warn"])


class AnsibleParseTests(unittest.TestCase):
    """Tests for Ansible ad-hoc stdout parsing helpers."""

    def test_parse_shell_line(self) -> None:
        """Parse df output tokens from ansible one-line shell results."""
        line = (
            "worker4 | SUCCESS | rc=0 | (stdout) root_use_percent=79 "
            "root_size=48G root_used=35G root_avail=9.4G"
        )
        host, stats = _parse_ansible_shell_line(line)
        self.assertEqual(host, "worker4")
        assert stats is not None
        self.assertEqual(stats["root_use_percent"], 79.0)
        self.assertEqual(stats["root_avail"], "9.4G")


if __name__ == "__main__":
    unittest.main()
