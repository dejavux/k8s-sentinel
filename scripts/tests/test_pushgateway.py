"""Pushgateway client tests."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from metrics.pushgateway import push_prometheus_metrics


class PushgatewayTests(unittest.TestCase):
    """push_prometheus_metrics PUTs text to job endpoint."""

    @patch("metrics.pushgateway.urllib.request.urlopen")
    def test_put_metrics(self, mock_urlopen: MagicMock) -> None:
        response = MagicMock()
        response.status = 200
        response.__enter__ = MagicMock(return_value=response)
        response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = response

        push_prometheus_metrics(
            "http://pushgateway:9091",
            "k8s-sentinel",
            "sentinel_check_status{module=\"disk\"} 0\n",
        )

        mock_urlopen.assert_called_once()
        request = mock_urlopen.call_args[0][0]
        self.assertEqual(request.get_method(), "PUT")
        self.assertIn("/metrics/job/k8s-sentinel", request.full_url)


if __name__ == "__main__":
    unittest.main()
