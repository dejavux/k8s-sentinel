"""Prometheus metrics rendering tests."""

from __future__ import annotations

import unittest

from checks.base import CheckResult
from metrics.prometheus import render_prometheus_metrics


class PrometheusMetricsTests(unittest.TestCase):
    """render_prometheus_metrics emits text exposition."""

    def test_includes_module_status(self) -> None:
        results = {
            "disk": CheckResult(module="disk", status="ok", message="ok"),
            "resources": CheckResult(
                module="resources",
                status="warning",
                message="warn",
                affected_nodes=["worker1"],
                details={"nodes": {"worker1": {"signals": ["MemoryPressure=True"]}}},
            ),
        }
        text = render_prometheus_metrics(results)
        self.assertIn('sentinel_check_status{module="disk"} 0', text)
        self.assertIn('sentinel_check_status{module="resources"} 1', text)
        self.assertIn('sentinel_node_resource_pressure{node="worker1"} 1', text)


if __name__ == "__main__":
    unittest.main()
