"""Tests for optional Telegram summary notifications."""

import os
import unittest
from unittest.mock import MagicMock, patch

from checks.base import CheckResult, FixResult
from notify.telegram import (
    build_summary_message,
    maybe_send_telegram_summary,
    should_send_summary,
)


class TelegramSummaryTests(unittest.TestCase):
    """Summary content and send gating."""

    def test_should_send_when_fixes_ran(self) -> None:
        checks = {
            "pods": CheckResult(module="pods", status="ok", message="healthy"),
        }
        fixes = {
            "components": FixResult(
                module="components",
                success=True,
                message="restarted kube-proxy",
                fixed_nodes=["n1"],
                failed_nodes=[],
            ),
        }
        self.assertTrue(should_send_summary(checks, fixes))

    def test_should_not_send_when_all_ok_and_no_fixes(self) -> None:
        checks = {
            "pods": CheckResult(module="pods", status="ok", message="healthy"),
        }
        self.assertFalse(should_send_summary(checks, None))

    def test_build_includes_pr_url(self) -> None:
        checks = {
            "pods": CheckResult(module="pods", status="error", message="bad"),
        }
        body = build_summary_message(
            checks,
            None,
            pr_result={"success": True, "pr_url": "https://github.com/o/r/pull/1"},
        )
        self.assertIn("pull/1", body)

    @patch("notify.telegram.send_telegram_message", return_value=True)
    def test_maybe_send_respects_disable_flag(self, mock_send: MagicMock) -> None:
        checks = {
            "pods": CheckResult(module="pods", status="error", message="bad"),
        }
        with patch.dict(os.environ, {"SENTINEL_TELEGRAM_NOTIFY": "false"}, clear=False):
            maybe_send_telegram_summary(checks, None)
        mock_send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
