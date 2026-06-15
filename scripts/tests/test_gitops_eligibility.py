"""Tests for GitOps PR eligibility (autoPR trigger narrowing)."""

import os
import unittest
from unittest.mock import patch

from checks.base import CheckResult, FixResult
from gitops.eligibility import (
    gitops_modules,
    module_needs_gitops,
    should_create_fix_pr,
)


def _check(
    module: str,
    *,
    status: str = "error",
    needs_gitops: bool = False,
) -> CheckResult:
    return CheckResult(
        module=module,
        status=status,
        message=f"{module} check",
        details={"needs_gitops": needs_gitops} if needs_gitops else {},
    )


def _fix(
    module: str,
    *,
    success: bool = False,
    needs_gitops: bool = False,
) -> FixResult:
    return FixResult(
        module=module,
        success=success,
        message=f"{module} fix",
        fixed_nodes=[],
        failed_nodes=["node-a"] if not success else [],
        details={"needs_gitops": needs_gitops} if needs_gitops else {},
    )


class GitopsModulesTests(unittest.TestCase):
    """gitops_modules parses SENTINEL_GITOPS_MODULES."""

    def test_default_is_pods(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("SENTINEL_GITOPS_MODULES", None)
            self.assertEqual(gitops_modules(), frozenset({"pods"}))

    def test_none_disables(self) -> None:
        with patch.dict(os.environ, {"SENTINEL_GITOPS_MODULES": "none"}):
            self.assertEqual(gitops_modules(), frozenset())


class ShouldCreateFixPrTests(unittest.TestCase):
    """should_create_fix_pr only fires for allowlisted needs_gitops modules."""

    def test_pods_needs_gitops_when_auto_pr_on(self) -> None:
        checks = {"pods": _check("pods", needs_gitops=True)}
        env = {"SENTINEL_AUTO_PR": "true", "SENTINEL_GITOPS_MODULES": "pods"}
        with patch.dict(os.environ, env, clear=False):
            self.assertTrue(should_create_fix_pr(checks, {}))

    def test_components_fix_failure_does_not_open_pr(self) -> None:
        checks = {"components": _check("components")}
        fixes = {"components": _fix("components", success=False)}
        env = {"SENTINEL_AUTO_PR": "true", "SENTINEL_GITOPS_MODULES": "pods"}
        with patch.dict(os.environ, env, clear=False):
            self.assertFalse(should_create_fix_pr(checks, fixes))

    def test_respects_module_allowlist(self) -> None:
        checks = {"pods": _check("pods", needs_gitops=True)}
        env = {"SENTINEL_AUTO_PR": "true", "SENTINEL_GITOPS_MODULES": "none"}
        with patch.dict(os.environ, env, clear=False):
            self.assertFalse(should_create_fix_pr(checks, {}))

    def test_fix_metadata_can_trigger_pods_gitops(self) -> None:
        checks = {"pods": _check("pods")}
        fixes = {"pods": _fix("pods", success=False, needs_gitops=True)}
        env = {"SENTINEL_AUTO_PR": "true", "SENTINEL_GITOPS_MODULES": "pods"}
        with patch.dict(os.environ, env, clear=False):
            self.assertTrue(should_create_fix_pr(checks, fixes))


class ModuleNeedsGitopsTests(unittest.TestCase):
    """module_needs_gitops reads check/fix details."""

    def test_reads_check_details(self) -> None:
        checks = {"pods": _check("pods", needs_gitops=True)}
        self.assertTrue(module_needs_gitops("pods", checks, None))

    def test_reads_fix_details(self) -> None:
        checks = {"pods": _check("pods")}
        fixes = {"pods": _fix("pods", needs_gitops=True)}
        self.assertTrue(module_needs_gitops("pods", checks, fixes))


if __name__ == "__main__":
    unittest.main()
