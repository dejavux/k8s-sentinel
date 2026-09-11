"""Tests for GitOps issue classification (runtime vs manifest)."""

import unittest

from gitops.issue_classifier import classify_issue_gitops


class IssueClassifierTests(unittest.TestCase):
    def test_worker_unreachable_pending_not_gitops(self) -> None:
        issue = {
            "problem": "Pending",
            "pending_category": "unknown",
            "scheduling_message": "node worker3 is unreachable",
            "events": [],
        }
        self.assertFalse(classify_issue_gitops(issue))

    def test_cni0_flannel_pending_not_gitops(self) -> None:
        issue = {
            "problem": "Pending",
            "pending_category": "unknown",
            "scheduling_message": "cni0 IP mismatch with flannel subnet",
            "events": [],
        }
        self.assertFalse(classify_issue_gitops(issue))

    def test_disk_pressure_pending_not_gitops(self) -> None:
        issue = {
            "problem": "Pending",
            "pending_category": "disk_pressure",
            "events": ["disk-pressure on node"],
        }
        self.assertFalse(classify_issue_gitops(issue))

    def test_pvc_unbound_pending_is_gitops(self) -> None:
        issue = {
            "problem": "Pending",
            "pending_category": "pvc_unbound",
            "pvc_claims": ["data-pvc"],
            "events": [],
        }
        self.assertTrue(classify_issue_gitops(issue))

    def test_configmap_mismatch_is_gitops(self) -> None:
        issue = {
            "problem": "CrashLoopBackOff",
            "configmap_mismatch": {"configmap": "loki/local-config"},
        }
        self.assertTrue(classify_issue_gitops(issue))

    def test_crashloop_without_cm_not_gitops(self) -> None:
        issue = {
            "problem": "CrashLoopBackOff",
            "events": ["Back-off restarting failed container"],
        }
        self.assertFalse(classify_issue_gitops(issue))

    def test_image_pull_gitops(self) -> None:
        issue = {
            "problem": "ImagePullBackOff",
            "events": ["Failed to pull image"],
        }
        self.assertTrue(classify_issue_gitops(issue))

    def test_evicted_not_gitops(self) -> None:
        issue = {
            "problem": "Evicted",
            "eviction_message": "Pod was evicted due to disk pressure",
        }
        self.assertFalse(classify_issue_gitops(issue))


if __name__ == "__main__":
    unittest.main()
