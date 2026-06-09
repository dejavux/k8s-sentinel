"""Unit tests for resources check."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from checks.resources_check import ResourcesCheck, _parse_kubectl_top_nodes


class ResourcesCheckTests(unittest.TestCase):
    """ResourcesCheck pressure and top parsing."""

    def test_parse_kubectl_top_nodes(self) -> None:
        sample = "worker1   120m   15%   4096Mi   42%\n"
        with patch("checks.resources_check.subprocess.run") as mock_run:
            mock_run.return_value.stdout = sample
            mock_run.return_value.returncode = 0
            result = _parse_kubectl_top_nodes()
        self.assertIn("worker1", result)
        self.assertEqual(result["worker1"]["cpu_percent"], 15.0)
        self.assertEqual(result["worker1"]["memory_percent"], 42.0)

    def test_memory_pressure_warning(self) -> None:
        nodes = [
            {
                "metadata": {"name": "worker1"},
                "status": {
                    "conditions": [
                        {"type": "MemoryPressure", "status": "True"},
                        {"type": "Ready", "status": "True"},
                    ]
                },
            }
        ]
        check = ResourcesCheck()
        with patch("checks.resources_check.get_nodes_json", return_value=nodes):
            with patch("checks.resources_check._parse_kubectl_top_nodes", return_value={}):
                result = check.check()
        self.assertEqual(result.status, "warning")
        self.assertIn("worker1", result.affected_nodes)


if __name__ == "__main__":
    unittest.main()
