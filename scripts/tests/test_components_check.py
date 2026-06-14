"""Unit tests for ComponentsCheck pod problem detection."""

from __future__ import annotations

import unittest

from checks.components_check import ComponentsCheck


def _pod(
    *,
    phase: str = "Running",
    ready: bool = True,
    waiting_reason: str | None = None,
) -> dict:
    state: dict = {"running": {"startedAt": "2026-06-14T00:00:00Z"}}
    if waiting_reason:
        state = {"waiting": {"reason": waiting_reason}}
    return {
        "metadata": {"name": "test-pod", "namespace": "kube-system"},
        "status": {
            "phase": phase,
            "containerStatuses": [
                {
                    "name": "main",
                    "ready": ready,
                    "state": state,
                }
            ],
        },
    }


class ComponentsCheckTests(unittest.TestCase):
    """ComponentsCheck._pod_problem edge cases."""

    def setUp(self) -> None:
        self.check = ComponentsCheck()

    def test_running_ready_is_healthy(self) -> None:
        self.assertIsNone(self.check._pod_problem(_pod(ready=True)))

    def test_running_not_ready_is_unhealthy(self) -> None:
        problem = self.check._pod_problem(_pod(ready=False))
        self.assertEqual(problem, "Container not ready")

    def test_crashloop_still_detected(self) -> None:
        problem = self.check._pod_problem(
            _pod(ready=False, waiting_reason="CrashLoopBackOff")
        )
        self.assertEqual(problem, "Container waiting: CrashLoopBackOff")

    def test_succeeded_phase_is_healthy(self) -> None:
        self.assertIsNone(self.check._pod_problem(_pod(phase="Succeeded", ready=False)))


if __name__ == "__main__":
    unittest.main()
