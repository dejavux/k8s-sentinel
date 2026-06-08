"""
K8s Sentinel - 平台組件健康檢查（kube-proxy、CoreDNS、MetalLB 等）

移植自 scripts/k8s-component-recovery.py；check 僅掃描，fix 重啟不健康 Pod。
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from json import JSONDecodeError
from typing import Any

from .base import BaseCheck, CheckResult, FixResult

BAD_WAIT_REASONS = frozenset(
    {
        "CrashLoopBackOff",
        "ImagePullBackOff",
        "ErrImagePull",
        "CreateContainerConfigError",
    }
)

MAX_RESTARTS = int(os.getenv("SENTINEL_COMPONENTS_MAX_RESTARTS", "3"))


@dataclass(frozen=True)
class ComponentSpec:
    """以名稱、命名空間與 label selector 描述要檢查的叢集元件。"""

    name: str
    namespace: str
    selectors: dict[str, str]


DEFAULT_COMPONENTS: tuple[ComponentSpec, ...] = (
    ComponentSpec("kube-proxy", "kube-system", {"k8s-app": "kube-proxy"}),
    ComponentSpec("kube-flannel", "kube-flannel", {"app": "flannel", "tier": "node"}),
    ComponentSpec(
        "metallb-controller",
        "metallb-system",
        {"app": "metallb", "component": "controller"},
    ),
    ComponentSpec(
        "metallb-speaker",
        "metallb-system",
        {"app": "metallb", "component": "speaker"},
    ),
    ComponentSpec("coredns", "kube-system", {"k8s-app": "kube-dns"}),
    ComponentSpec(
        "ingress-nginx",
        "ingress-nginx",
        {
            "app.kubernetes.io/name": "ingress-nginx",
            "app.kubernetes.io/component": "controller",
        },
    ),
    ComponentSpec(
        "docker-registry",
        "default",
        {"app.kubernetes.io/name": "docker-registry"},
    ),
    ComponentSpec(
        "1password-connect",
        "1password",
        {"app.kubernetes.io/name": "1password-connect"},
    ),
    ComponentSpec("promtail", "monitoring", {"app.kubernetes.io/name": "promtail"}),
)


class ComponentsCheck(BaseCheck):
    """平台組件 Pod 健康檢查與重啟修復"""

    @property
    def name(self) -> str:
        return "components"

    @property
    def description(self) -> str:
        return "檢查 kube-proxy/CoreDNS/MetalLB 等平台組件 Pod 並重啟異常 workload"

    def check(self) -> CheckResult:
        self.logger.info("Starting %s check...", self.name)
        try:
            issues: list[dict[str, Any]] = []
            for spec in DEFAULT_COMPONENTS:
                unhealthy = self._unhealthy_pods(spec)
                if unhealthy:
                    issues.append(
                        {
                            "component": spec.name,
                            "namespace": spec.namespace,
                            "unhealthy_pods": unhealthy,
                        }
                    )

            if not issues:
                return CheckResult(
                    module=self.name,
                    status="ok",
                    message=f"All {len(DEFAULT_COMPONENTS)} platform component(s) healthy",
                    details={
                        "components_checked": len(DEFAULT_COMPONENTS),
                        "issues": [],
                    },
                )

            names = [item["component"] for item in issues]
            return CheckResult(
                module=self.name,
                status="error",
                message=f"Unhealthy platform component(s): {', '.join(names)}",
                details={
                    "components_checked": len(DEFAULT_COMPONENTS),
                    "issues": issues,
                },
                affected_nodes=names,
            )
        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            JSONDecodeError,
            OSError,
        ) as exc:
            self.logger.exception("Error during %s check", self.name)
            return CheckResult(
                module=self.name,
                status="error",
                message=f"Check failed: {exc}",
                details={"error": str(exc)},
            )

    def can_auto_fix(self) -> bool:
        return True

    def fix(self, check_result: CheckResult) -> FixResult:
        if check_result.is_healthy():
            return FixResult(
                module=self.name,
                success=True,
                message="No component issues to fix",
                fixed_nodes=[],
                failed_nodes=[],
            )

        issues = (check_result.details or {}).get("issues") or []
        fixed: list[str] = []
        failed: list[str] = []
        actions: list[dict[str, Any]] = []

        for issue in issues:
            component = issue.get("component", "")
            namespace = issue.get("namespace", "")
            restarts = 0
            for pod in issue.get("unhealthy_pods") or []:
                if restarts >= MAX_RESTARTS:
                    self.logger.warning(
                        "Max restarts (%d) reached for %s", MAX_RESTARTS, component
                    )
                    break
                pod_name = pod.get("name", "")
                ref = f"{namespace}/{pod_name}"
                if self._restart_pod(namespace, pod_name, pod):
                    fixed.append(ref)
                    restarts += 1
                    actions.append(
                        {"pod": ref, "component": component, "action": "restarted"}
                    )
                else:
                    failed.append(ref)
                time.sleep(2)

        return FixResult(
            module=self.name,
            success=len(failed) == 0,
            message=f"Restarted {len(fixed)} pod(s), {len(failed)} failed",
            fixed_nodes=fixed,
            failed_nodes=failed,
            details={"actions": actions, "max_restarts_per_component": MAX_RESTARTS},
        )

    def _kubectl(self, args: list[str]) -> tuple[bool, str]:
        try:
            proc = subprocess.run(
                ["kubectl", *args],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            return proc.returncode == 0, proc.stdout.strip()
        except (subprocess.TimeoutExpired, OSError) as exc:
            self.logger.error("kubectl failed: %s", exc)
            return False, ""

    def _unhealthy_pods(self, spec: ComponentSpec) -> list[dict[str, Any]]:
        label = ",".join(f"{k}={v}" for k, v in spec.selectors.items())
        ok, output = self._kubectl(
            ["get", "pods", "-n", spec.namespace, "-l", label, "-o", "json"]
        )
        if not ok or not output:
            return []

        try:
            items = json.loads(output).get("items", [])
        except JSONDecodeError:
            return []

        unhealthy: list[dict[str, Any]] = []
        for pod in items:
            problem = self._pod_problem(pod)
            if problem:
                meta = pod.get("metadata", {})
                unhealthy.append(
                    {
                        "name": meta.get("name"),
                        "phase": pod.get("status", {}).get("phase"),
                        "node": pod.get("spec", {}).get("nodeName"),
                        "reason": problem,
                    }
                )
        return unhealthy

    def _pod_problem(self, pod: dict[str, Any]) -> str | None:
        status = pod.get("status", {})
        phase = status.get("phase", "")
        if phase not in ("Running", "Succeeded"):
            return f"Pod phase: {phase}"

        for container in status.get("containerStatuses") or []:
            state = container.get("state") or {}
            waiting = state.get("waiting") or {}
            reason = waiting.get("reason")
            if reason in BAD_WAIT_REASONS:
                return f"Container waiting: {reason}"
            terminated = state.get("terminated") or {}
            term_reason = terminated.get("reason")
            if term_reason and term_reason != "Completed":
                return f"Container terminated: {term_reason}"
        return None

    def _restart_pod(
        self, namespace: str, pod_name: str, pod_info: dict[str, Any]
    ) -> bool:
        reason = pod_info.get("reason", "")
        args = ["delete", "pod", pod_name, "-n", namespace]
        if "Unknown" in reason or "ContainerStatusUnknown" in reason:
            args.extend(["--grace-period=0", "--force", "--ignore-not-found=true"])
        elif "CrashLoopBackOff" in reason or "Container waiting" in reason:
            args.extend(["--grace-period=5"])
        else:
            args.extend(["--grace-period=10"])

        ok, _ = self._kubectl(args)
        if ok:
            self.logger.info("Restarted pod %s/%s", namespace, pod_name)
        return ok
