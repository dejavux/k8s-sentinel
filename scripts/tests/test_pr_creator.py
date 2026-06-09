"""Tests for GitOps PR branch slug sanitization and open-PR guard."""

import os
import unittest
from unittest.mock import MagicMock, patch

from gitops.pr_creator import (
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


if __name__ == "__main__":
    unittest.main()
