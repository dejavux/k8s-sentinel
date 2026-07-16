"""Tests for GitOps PR branch slug sanitization and open-PR guard."""

import os
import unittest
from unittest.mock import MagicMock, patch

from gitops.pr_creator import (
    build_fallback_pr_meta,
    count_open_sentinel_prs,
    generate_pr_meta,
    open_sentinel_pr_limit_reached,
    sanitize_git_branch_slug,
)


class SanitizeBranchTests(unittest.TestCase):
    """sanitize_git_branch_slug produces valid git ref names."""

    def test_strips_spaces_from_module_list(self) -> None:
        """Comma-separated modules become a single slug without spaces."""
        branch = sanitize_git_branch_slug("runc, disk, pods, components")
        self.assertEqual(branch, "sentinel/fix-runc-disk-pods-components")
        self.assertNotIn(" ", branch)

    def test_empty_slug_uses_run(self) -> None:
        """Whitespace-only input falls back to sentinel/fix-run."""
        branch = sanitize_git_branch_slug("   ")
        self.assertEqual(branch, "sentinel/fix-run")


class OpenPrGuardTests(unittest.TestCase):
    """open_sentinel_pr_limit_reached respects SENTINEL_MAX_OPEN_PRS."""

    @patch("gitops.pr_creator.gh_cmd")
    def test_blocks_when_open_pr_exists(self, mock_gh: MagicMock) -> None:
        mock_gh.return_value = MagicMock(
            returncode=0,
            stdout='[{"headRefName": "sentinel/fix-pods"}]',
            stderr="",
        )
        with patch.dict("os.environ", {"SENTINEL_MAX_OPEN_PRS": "1"}):
            self.assertTrue(open_sentinel_pr_limit_reached(MagicMock()))
        self.assertEqual(count_open_sentinel_prs(MagicMock()), 1)

    @patch("gitops.pr_creator.gh_cmd")
    def test_allows_when_under_limit(self, mock_gh: MagicMock) -> None:
        mock_gh.return_value = MagicMock(returncode=0, stdout="[]", stderr="")
        with patch.dict("os.environ", {"SENTINEL_MAX_OPEN_PRS": "1"}):
            self.assertFalse(open_sentinel_pr_limit_reached(MagicMock()))


class GeneratePrMetaTests(unittest.TestCase):
    """generate_pr_meta fallback when Cursor is unavailable."""

    def test_fallback_without_cursor_key(self) -> None:
        payload = {
            "checks": {
                "pods": {"status": "error", "message": "unhealthy pods"},
            }
        }
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("CURSOR_API_KEY", None)
            meta = generate_pr_meta(payload)
        self.assertIn("pods", meta["title"])
        self.assertTrue(meta["branch"].startswith("sentinel/fix-"))


class BuildFallbackPrMetaTests(unittest.TestCase):
    """build_fallback_pr_meta produces runbook files for Pending pods."""

    def test_pending_issue_produces_runbook_file(self) -> None:
        payload = {
            "checks": {
                "pods": {
                    "status": "warning",
                    "details": {
                        "issues": [
                            {
                                "namespace": "vpn-egress",
                                "name": "vpn-verify",
                                "problem": "Pending",
                                "pending_category": "node_affinity",
                                "node_selector": {"vpn-egress": "true"},
                                "scheduling_message": "didn't match pod's node affinity",
                                "events": ["FailedScheduling: node affinity"],
                            }
                        ]
                    },
                }
            }
        }
        meta = build_fallback_pr_meta(payload)
        self.assertTrue(meta["files"])
        self.assertIn("vpn-egress", meta["files"][0]["path"])
        self.assertIn("vpn-verify", meta["files"][0]["content"])
        self.assertIn("kubectl label node", meta["files"][0]["content"])

    def test_generate_pr_meta_uses_fallback_when_cursor_empty(self) -> None:
        payload = {
            "checks": {
                "pods": {
                    "details": {
                        "issues": [
                            {
                                "namespace": "vpn-egress",
                                "name": "vpn-verify",
                                "problem": "Pending",
                                "pending_category": "unknown",
                            }
                        ]
                    }
                }
            }
        }
        with patch("gitops.pr_creator.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='{"title":"x","body":"y","branch":"sentinel/fix-x","files":[]}',
                stderr="",
            )
            with patch.dict(os.environ, {"CURSOR_API_KEY": "test-key"}):
                with patch(
                    "gitops.pr_creator._cursor_script_path",
                    return_value=MagicMock(is_file=lambda: True),
                ):
                    meta = generate_pr_meta(payload)
        self.assertTrue(meta.get("files"))
        self.assertIn("runbooks", meta["files"][0]["path"])


if __name__ == "__main__":
    unittest.main()
