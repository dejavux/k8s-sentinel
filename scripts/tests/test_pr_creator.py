"""Tests for GitOps PR branch slug sanitization."""

import unittest

from gitops.pr_creator import sanitize_git_branch_slug


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


if __name__ == "__main__":
    unittest.main()
