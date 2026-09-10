"""
K8s Sentinel - Pod 異常掃描與修復

掃描 CrashLoopBackOff、Pending、Terminating、NotReady 等問題 Pod，
執行叢集內安全修復，並收集診斷供 Cursor SDK 開 PR。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from json import JSONDecodeError
from typing import Any

from .base import BaseCheck, CheckResult, FixResult

PROBLEM_REASONS = frozenset(
    {
        "CrashLoopBackOff",
        "Error",
        "ImagePullBackOff",
        "ErrImagePull",
        "CreateContainerConfigError",
        "RunContainerError",
        "Evicted",
    }
)

DISK_EVICTION_MARKERS = (
    "disk pressure",
    "diskpressure",
    "ephemeral",
    "nodefs",
    "imagefs",
    "containerfs",
    "emptydir",
)

PVC_DISK_FULL_MARKERS = (
    "no space left on device",
    "errno 28",
    "enospc",
)

TERMINATING_MAX_SEC = int(os.getenv("SENTINEL_POD_TERMINATING_MAX_SEC", "3600"))
PENDING_MAX_SEC = int(os.getenv("SENTINEL_POD_PENDING_MAX_SEC", "1800"))
NOT_READY_MAX_SEC = int(os.getenv("SENTINEL_POD_NOT_READY_MAX_SEC", "900"))
NOTREADY_AUTO_FIX_OWNER_KINDS = frozenset({"DaemonSet"})
LOG_TAIL = int(os.getenv("SENTINEL_POD_LOG_TAIL", "40"))
CONFIG_FILE_RE = re.compile(r"-config\.file=([^\s]+)")


class PodCheck(BaseCheck):
    """全叢集 Pod 異常掃描與修復"""

    @property
    def name(self) -> str:
        return "pods"

    @property
    def description(self) -> str:
        return "掃描異常 Pod（CrashLoop、Pending、Terminating、NotReady）並嘗試修復"

    def check(self) -> CheckResult:
        self.logger.info("Starting %s check...", self.name)
        try:
            pods = self._list_pods()
            issues: list[dict[str, Any]] = []

            for pod in pods:
                issue = self._analyze_pod(pod)
                if issue:
                    issues.append(issue)

            if not issues:
                return CheckResult(
                    module=self.name,
                    status="ok",
                    message=f"No problematic pods among {len(pods)} scanned",
                    details={"scanned": len(pods), "issues": []},
                )

            counts: dict[str, int] = {}
            for item in issues:
                problem = item.get("problem", "unknown")
                counts[problem] = counts.get(problem, 0) + 1

            needs_gitops = any(item.get("needs_gitops") for item in issues)
            status = (
                "error"
                if any(
                    item.get("problem") in PROBLEM_REASONS
                    or item.get("problem") == "NotReady"
                    for item in issues
                )
                else "warning"
            )

            return CheckResult(
                module=self.name,
                status=status,
                message=f"Found {len(issues)} problematic pod(s)",
                details={
                    "scanned": len(pods),
                    "issues": issues,
                    "counts": counts,
                    "needs_gitops": needs_gitops,
                },
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
                message="No pod issues to fix",
                fixed_nodes=[],
                failed_nodes=[],
            )

        issues = (check_result.details or {}).get("issues") or []
        fixed: list[str] = []
        failed: list[str] = []
        actions: list[dict[str, Any]] = []

        for issue in issues:
            ns = issue.get("namespace", "")
            name = issue.get("name", "")
            ref = f"{ns}/{name}"
            problem = issue.get("problem", "")

            if problem == "Terminating":
                if self._force_delete_pod(ns, name):
                    fixed.append(ref)
                    actions.append({"pod": ref, "action": "force_deleted"})
                else:
                    failed.append(ref)
                continue

            if problem == "Evicted":
                if self._delete_evicted_pod(ns, name):
                    fixed.append(ref)
                    actions.append({"pod": ref, "action": "deleted_evicted"})
                else:
                    failed.append(ref)
                continue

            if issue.get("configmap_mismatch"):
                patched = self._patch_configmap_key(issue["configmap_mismatch"])
                if patched:
                    fixed.append(ref)
                    actions.append(
                        {"pod": ref, "action": "configmap_patched", **patched}
                    )
                    continue

            if problem in PROBLEM_REASONS and issue.get("owner_kind") == "ReplicaSet":
                if self._delete_stale_replicaset_pod(issue):
                    fixed.append(ref)
                    actions.append({"pod": ref, "action": "deleted_stale_rs_pod"})
                    continue

            if problem in PROBLEM_REASONS:
                if issue.get("pvc_disk_full"):
                    actions.append(
                        {
                            "pod": ref,
                            "action": "diagnosed_only",
                            "reason": "pvc_disk_full",
                            "remediation": (
                                "40_k8s/playbooks/maintenance/"
                                "free-grid-bot-shared-services-storage.yml"
                            ),
                        }
                    )
                    continue
                if self._restart_pod(ns, name):
                    fixed.append(ref)
                    actions.append({"pod": ref, "action": "restarted"})
                else:
                    failed.append(ref)
                continue

            if problem == "Pending":
                if self._tekton_scheduling_stuck(issue) and self._unstick_tekton_pending(
                    issue
                ):
                    fixed.append(ref)
                    actions.append(
                        {
                            "pod": ref,
                            "action": "unstuck_tekton_workspace",
                            "events": issue.get("events", []),
                        }
                    )
                else:
                    actions.append(
                        {
                            "pod": ref,
                            "action": "diagnosed_only",
                            "pending_category": issue.get("pending_category"),
                            "scheduling_message": issue.get("scheduling_message"),
                            "events": issue.get("events", []),
                        }
                    )
                continue

            if problem == "NotReady":
                if issue.get("auto_fixable"):
                    # Bare Pod + leftover sidecar: delete (no controller to recreate).
                    # DaemonSet NotReady: delete so kubelet recreates.
                    if self._restart_pod(ns, name):
                        fixed.append(ref)
                        action = (
                            "deleted_stale_bare_sidecar"
                            if issue.get("stale_bare_sidecar")
                            else "restarted"
                        )
                        actions.append({"pod": ref, "action": action})
                    else:
                        failed.append(ref)
                else:
                    actions.append({"pod": ref, "action": "diagnosed_only"})
                continue

        remaining = [i for i in issues if f"{i['namespace']}/{i['name']}" not in fixed]
        needs_gitops = any(i.get("needs_gitops") for i in remaining)

        return FixResult(
            module=self.name,
            success=len(failed) == 0,
            message=(
                f"Fixed {len(fixed)} pod(s), {len(failed)} failed, "
                f"{len(remaining)} still need attention"
            ),
            fixed_nodes=fixed,
            failed_nodes=failed,
            details={
                "actions": actions,
                "remaining_issues": remaining,
                "needs_gitops": needs_gitops,
            },
        )

    def _list_pods(self) -> list[dict[str, Any]]:
        result = subprocess.run(
            ["kubectl", "get", "pods", "-A", "-o", "json"],
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )
        data = json.loads(result.stdout)
        return data.get("items", [])

    def _analyze_pod(self, pod: dict[str, Any]) -> dict[str, Any] | None:
        meta = pod.get("metadata", {})
        # Sentinel CronJob Job pods intentionally end Failed when checks exit non-zero;
        # counting them triggers self-referential pod issues and non-actionable fixes.
        if self._is_own_sentinel_batch_pod(pod):
            return None
        status = pod.get("status", {})
        ns = meta.get("namespace", "")
        name = meta.get("name", "")
        phase = status.get("phase", "")
        now = datetime.now(timezone.utc)
        issue: dict[str, Any] | None = None

        if meta.get("deletionTimestamp"):
            age_sec = self._age_seconds(meta["deletionTimestamp"], now)
            if age_sec >= TERMINATING_MAX_SEC:
                issue = self._issue(
                    pod,
                    problem="Terminating",
                    age_sec=age_sec,
                    auto_fixable=True,
                )
        elif phase == "Pending":
            age_sec = self._age_seconds(meta.get("creationTimestamp"), now)
            events = self._pod_events(ns, name)
            disk_pressure_pending = self._events_indicate_disk_pressure(events)
            if age_sec >= PENDING_MAX_SEC or disk_pressure_pending:
                pending_diag = self._pending_diagnostics(pod, events)
                issue = self._issue(
                    pod,
                    problem="Pending",
                    age_sec=age_sec,
                    needs_gitops=True,
                    extra={
                        "events": events,
                        "disk_pressure_pending": disk_pressure_pending,
                        **pending_diag,
                    },
                )
        elif phase == "Failed":
            reason = status.get("reason") or ""
            message = status.get("message") or ""
            if reason == "Evicted" or "evicted" in message.lower():
                disk_related = self._is_disk_eviction(message)
                issue = self._issue(
                    pod,
                    problem="Evicted",
                    age_sec=self._age_seconds(meta.get("creationTimestamp"), now),
                    needs_gitops=disk_related,
                    auto_fixable=True,
                    extra={
                        "node": pod.get("spec", {}).get("nodeName"),
                        "eviction_message": message,
                        "disk_related": disk_related,
                        "qos_class": pod.get("status", {}).get("qosClass"),
                        "events": self._pod_events(ns, name),
                    },
                )
        else:
            container_problem = self._container_problem(pod)
            if container_problem:
                issue = self._issue(
                    pod,
                    problem=container_problem,
                    age_sec=self._age_seconds(meta.get("creationTimestamp"), now),
                    needs_gitops=True,
                    extra={
                        "logs": self._pod_logs(ns, name),
                        "events": self._pod_events(ns, name),
                    },
                )
                logs = issue.get("logs", "")
                if self._logs_indicate_pvc_full(logs):
                    issue["pvc_disk_full"] = True
                    issue["auto_fixable"] = False
                    issue["needs_gitops"] = True
                cm_hint = self._configmap_mismatch(pod, logs)
                if cm_hint:
                    issue["configmap_mismatch"] = cm_hint
                    issue["needs_gitops"] = True
                    issue["auto_fixable"] = True
            elif phase == "Running" and not self._pod_ready(pod):
                age_sec = self._unready_age_seconds(pod, now)
                if age_sec >= NOT_READY_MAX_SEC:
                    owner_kind, _owner_name = self._owner(meta)
                    stale_sidecar = self._is_stale_bare_sidecar_pod(pod)
                    auto_fixable = (
                        owner_kind in NOTREADY_AUTO_FIX_OWNER_KINDS or stale_sidecar
                    )
                    issue = self._issue(
                        pod,
                        problem="NotReady",
                        age_sec=age_sec,
                        # Bare smoke pods are cluster cleanup, not GitOps.
                        needs_gitops=not auto_fixable,
                        auto_fixable=auto_fixable,
                        extra={
                            "logs": self._pod_logs(ns, name),
                            "events": self._pod_events(ns, name),
                            "stale_bare_sidecar": stale_sidecar,
                        },
                    )

        return issue

    def _is_own_sentinel_batch_pod(self, pod: dict[str, Any]) -> bool:
        """True for kube-system k8s-sentinel workload pods owned by a Job."""
        meta = pod.get("metadata", {}) or {}
        if meta.get("namespace") != "kube-system":
            return False
        labels = meta.get("labels") or {}
        if labels.get("app") != "k8s-sentinel":
            return False
        owner_kind, owner_name = self._owner(meta)
        if owner_kind != "Job" or not owner_name:
            return False
        return (
            owner_name.startswith("k8s-sentinel-")
            or owner_name.startswith("sentinel-manual-")
            or owner_name.startswith("sentinel-check-")
        )

    @staticmethod
    def _is_stale_bare_sidecar_pod(pod: dict[str, Any]) -> bool:
        """Bare Pod where workload finished but a sidecar (e.g. gluetun) still runs.

        Common anti-pattern: smoke/verify Completes, gluetun stays Running →
        Ready=False forever → Sentinel pods noise and SentinelModuleError.
        """
        meta = pod.get("metadata", {}) or {}
        owner_kind, _ = PodCheck._owner(meta)
        if owner_kind is not None:
            return False

        statuses = list(pod.get("status", {}).get("containerStatuses") or [])
        if len(statuses) < 2:
            return False

        names = {
            c.get("name")
            for c in (pod.get("spec", {}) or {}).get("containers") or []
            if c.get("name")
        }
        has_known_sidecar = bool(names & {"gluetun", "cloudsql-proxy", "istio-proxy"})

        completed_ok = False
        still_running = False
        for cs in statuses:
            state = cs.get("state") or {}
            terminated = state.get("terminated") or {}
            if terminated and int(terminated.get("exitCode", 1)) == 0:
                completed_ok = True
            if state.get("running"):
                still_running = True

        if completed_ok and still_running:
            return True
        # Gluetun health flap: both containers may still be Running but Ready=False
        return has_known_sidecar and still_running

    def _issue(
        self,
        pod: dict[str, Any],
        *,
        problem: str,
        age_sec: int,
        needs_gitops: bool = False,
        auto_fixable: bool = False,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        meta = pod.get("metadata", {})
        owner_kind, owner_name = self._owner(meta)
        item: dict[str, Any] = {
            "namespace": meta.get("namespace"),
            "name": meta.get("name"),
            "problem": problem,
            "phase": pod.get("status", {}).get("phase"),
            "age_sec": age_sec,
            "owner_kind": owner_kind,
            "owner_name": owner_name,
            "needs_gitops": needs_gitops,
            "auto_fixable": auto_fixable,
        }
        if extra:
            item.update(extra)
        return item

    @staticmethod
    def _owner(meta: dict[str, Any]) -> tuple[str | None, str | None]:
        for ref in meta.get("ownerReferences") or []:
            if ref.get("controller"):
                return ref.get("kind"), ref.get("name")
        return None, None

    @staticmethod
    def _age_seconds(ts: str | None, now: datetime) -> int:
        if not ts:
            return 0
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return max(0, int((now - parsed).total_seconds()))

    def _unready_age_seconds(self, pod: dict[str, Any], now: datetime) -> int:
        meta = pod.get("metadata", {})
        base = self._age_seconds(meta.get("creationTimestamp"), now)
        for cs in pod.get("status", {}).get("containerStatuses") or []:
            started = cs.get("state", {}).get("running", {}).get("startedAt")
            if started and not cs.get("ready"):
                return self._age_seconds(started, now)
        return base

    @staticmethod
    def _pod_ready(pod: dict[str, Any]) -> bool:
        conditions = {
            c.get("type"): c.get("status")
            for c in pod.get("status", {}).get("conditions") or []
        }
        return conditions.get("Ready") == "True"

    def _container_problem(self, pod: dict[str, Any]) -> str | None:
        statuses = list(pod.get("status", {}).get("initContainerStatuses") or [])
        statuses.extend(pod.get("status", {}).get("containerStatuses") or [])
        for cs in statuses:
            state = cs.get("state") or {}
            waiting = state.get("waiting") or {}
            reason = waiting.get("reason")
            if reason in PROBLEM_REASONS:
                return reason
            terminated = state.get("terminated") or {}
            if (
                terminated.get("reason") == "Error"
                and terminated.get("exitCode", 0) != 0
            ):
                return "Error"
        return None

    def _pod_logs(self, namespace: str, name: str) -> str:
        proc = subprocess.run(
            ["kubectl", "logs", "-n", namespace, name, "--tail", str(LOG_TAIL)],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if proc.returncode == 0:
            return proc.stdout[-4000:]
        return proc.stderr[-1000:]

    def _pod_events(self, namespace: str, name: str) -> list[str]:
        proc = subprocess.run(
            [
                "kubectl",
                "get",
                "events",
                "-n",
                namespace,
                "--field-selector",
                f"involvedObject.name={name}",
                "--sort-by=.lastTimestamp",
                "-o",
                "json",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if proc.returncode != 0:
            return []
        try:
            items = json.loads(proc.stdout).get("items", [])
        except JSONDecodeError:
            return []
        lines: list[str] = []
        for ev in items[-8:]:
            lines.append(
                f"{ev.get('reason')}: {ev.get('message')} "
                f"({ev.get('lastTimestamp') or ev.get('eventTime')})"
            )
        return lines

    def _configmap_mismatch(
        self, pod: dict[str, Any], logs: str
    ) -> dict[str, Any] | None:
        if "does not exist" not in logs and "no such file" not in logs.lower():
            return None

        expected_paths: list[str] = []
        for container in pod.get("spec", {}).get("containers") or []:
            for arg in container.get("args") or []:
                match = CONFIG_FILE_RE.search(arg)
                if match:
                    expected_paths.append(match.group(1))
            for env in container.get("env") or []:
                if env.get("name") == "CONFIG_FILE" and env.get("value"):
                    expected_paths.append(env["value"])

        if not expected_paths:
            return None

        ns = pod.get("metadata", {}).get("namespace", "")
        for vm in pod.get("spec", {}).get("volumes") or []:
            cm = vm.get("configMap")
            if not cm:
                continue
            cm_name = cm.get("name")
            if not cm_name:
                continue
            keys = self._configmap_keys(ns, cm_name)
            for path in expected_paths:
                basename = path.rsplit("/", 1)[-1]
                if basename in keys:
                    continue
                alt = self._find_similar_key(keys, basename)
                if alt:
                    return {
                        "namespace": ns,
                        "configmap": cm_name,
                        "expected_key": basename,
                        "existing_key": alt,
                        "mount_path": path,
                    }
        return None

    def _configmap_keys(self, namespace: str, name: str) -> dict[str, str]:
        proc = subprocess.run(
            ["kubectl", "get", "cm", "-n", namespace, name, "-o", "json"],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        if proc.returncode != 0:
            return {}
        try:
            data = json.loads(proc.stdout).get("data") or {}
        except JSONDecodeError:
            return {}
        return {str(k): str(v) for k, v in data.items()}

    @staticmethod
    def _find_similar_key(keys: dict[str, str], expected: str) -> str | None:
        base = expected.rsplit(".", 1)[0]
        for key in keys:
            if key == expected:
                return key
            if key.rsplit(".", 1)[0] == base and (
                key.endswith(".yaml") or key.endswith(".yml")
            ):
                return key
        for key in keys:
            if key.endswith(".yaml") or key.endswith(".yml"):
                return key
        return next(iter(keys), None)

    def _patch_configmap_key(self, hint: dict[str, Any]) -> dict[str, Any] | None:
        ns = hint["namespace"]
        name = hint["configmap"]
        expected = hint["expected_key"]
        existing = hint["existing_key"]
        keys = self._configmap_keys(ns, name)
        content = keys.get(existing)
        if not content or expected in keys:
            return None

        patch = {"data": {expected: content}}
        proc = subprocess.run(
            [
                "kubectl",
                "patch",
                "cm",
                "-n",
                ns,
                name,
                "--type",
                "merge",
                "-p",
                json.dumps(patch),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if proc.returncode != 0:
            self.logger.warning(
                "ConfigMap patch failed for %s/%s: %s", ns, name, proc.stderr
            )
            return None
        self.logger.info(
            "Patched ConfigMap %s/%s: added key %s from %s",
            ns,
            name,
            expected,
            existing,
        )
        return {
            "configmap": f"{ns}/{name}",
            "added_key": expected,
            "from_key": existing,
        }

    @staticmethod
    def _is_disk_eviction(message: str) -> bool:
        lowered = message.lower()
        normalized = lowered.replace("_", "").replace(" ", "")
        if any(marker.replace(" ", "") in normalized for marker in DISK_EVICTION_MARKERS):
            return True
        return any(marker in lowered for marker in DISK_EVICTION_MARKERS)

    @staticmethod
    def _logs_indicate_pvc_full(logs: str) -> bool:
        lowered = logs.lower()
        return any(marker in lowered for marker in PVC_DISK_FULL_MARKERS)

    @staticmethod
    def _events_indicate_disk_pressure(events: list[str]) -> bool:
        joined = " ".join(events).lower()
        return "disk-pressure" in joined or "disk pressure" in joined

    def _pending_diagnostics(
        self, pod: dict[str, Any], events: list[str]
    ) -> dict[str, Any]:
        """Collect scheduling context to speed up Pending triage and GitOps PRs."""
        spec = pod.get("spec", {}) or {}
        status = pod.get("status", {}) or {}
        diag: dict[str, Any] = {}

        for cond in status.get("conditions") or []:
            if cond.get("type") == "PodScheduled" and cond.get("status") != "True":
                diag["scheduling_reason"] = cond.get("reason")
                diag["scheduling_message"] = cond.get("message")
                break

        requests: dict[str, str] = {}
        for container in list(spec.get("initContainers") or []) + list(
            spec.get("containers") or []
        ):
            for resource, value in (
                (container.get("resources") or {}).get("requests") or {}
            ).items():
                requests[str(resource)] = str(value)
        if requests:
            diag["resource_requests"] = requests

        if spec.get("nodeSelector"):
            diag["node_selector"] = spec["nodeSelector"]

        if spec.get("affinity"):
            diag["has_affinity"] = True

        tolerations = spec.get("tolerations") or []
        if tolerations:
            diag["toleration_count"] = len(tolerations)

        pvc_claims = [
            pvc.get("claimName")
            for vol in spec.get("volumes") or []
            if (pvc := vol.get("persistentVolumeClaim"))
            and pvc.get("claimName")
        ]
        if pvc_claims:
            diag["pvc_claims"] = pvc_claims

        diag["pending_category"] = self._classify_pending(diag, events)
        return diag

    @staticmethod
    def _classify_pending(diag: dict[str, Any], events: list[str]) -> str:
        joined = " ".join(events).lower()
        msg = str(diag.get("scheduling_message") or "").lower()
        reason = str(diag.get("scheduling_reason") or "").lower()
        combined = f"{joined} {msg} {reason}"

        if "disk-pressure" in combined or "disk pressure" in combined:
            return "disk_pressure"
        if "didn't match pod's node affinity" in combined or "node affinity" in combined:
            return "node_affinity"
        if "didn't tolerate" in combined or "untolerated taint" in combined:
            return "taints"
        if "insufficient cpu" in combined:
            return "insufficient_cpu"
        if "insufficient memory" in combined or "insufficient hugepages" in combined:
            return "insufficient_memory"
        if "insufficient" in combined:
            return "insufficient_resources"
        if (
            "persistentvolumeclaim" in combined
            or "unbound immediate" in combined
            or diag.get("pvc_claims")
        ):
            return "pvc_unbound"
        if "quota" in combined or "exceeded quota" in combined:
            return "resource_quota"
        if "schedulingdisabled" in combined or "cordoned" in combined:
            return "node_cordoned"
        return "unknown"

    def _delete_evicted_pod(self, namespace: str, name: str) -> bool:
        proc = subprocess.run(
            ["kubectl", "delete", "pod", "-n", namespace, name, "--wait=false"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        ok = proc.returncode == 0
        if ok:
            self.logger.info("Deleted evicted pod %s/%s", namespace, name)
        return ok

    def _force_delete_pod(self, namespace: str, name: str) -> bool:
        proc = subprocess.run(
            [
                "kubectl",
                "delete",
                "pod",
                "-n",
                namespace,
                name,
                "--grace-period=0",
                "--force",
                "--wait=false",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        ok = proc.returncode == 0
        if ok:
            self.logger.info("Force deleted terminating pod %s/%s", namespace, name)
        return ok

    @staticmethod
    def _tekton_scheduling_stuck(issue: dict[str, Any]) -> bool:
        if issue.get("owner_kind") != "TaskRun":
            return False
        events = " ".join(issue.get("events") or []).lower()
        markers = (
            "pod affinity",
            "insufficient cpu",
            "failedscheduling",
        )
        return any(marker in events for marker in markers)

    def _unstick_tekton_pending(self, issue: dict[str, Any]) -> bool:
        namespace = issue.get("namespace", "")
        if not namespace:
            return False

        infra_root = Path(
            os.getenv("SENTINEL_INFRA_ROOT", "/workspace/infra-bootstrap")
        )
        script = Path(
            os.getenv(
                "SENTINEL_TEKTON_UNSTICK_SCRIPT",
                str(
                    infra_root
                    / "60_apps/tekton-ci/scripts/unstick-tekton-pending-workspaces.sh"
                ),
            )
        )
        if not script.is_file():
            self.logger.warning("Tekton unstick script not found: %s", script)
            return False

        pipelinerun = self._pipelinerun_from_taskrun(namespace, issue.get("owner_name"))
        cmd = ["bash", str(script), "--namespace", namespace]
        if pipelinerun:
            cmd.extend(["--pipelinerun", pipelinerun])

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        if proc.returncode != 0:
            self.logger.warning(
                "Tekton unstick failed for %s/%s: %s",
                namespace,
                issue.get("name"),
                proc.stderr[-500:],
            )
            return False
        self.logger.info(
            "Unstuck Tekton workspace for %s/%s (pipelinerun=%s)",
            namespace,
            issue.get("name"),
            pipelinerun or "*",
        )
        return True

    def _pipelinerun_from_taskrun(
        self, namespace: str, taskrun_name: str | None
    ) -> str | None:
        if not namespace or not taskrun_name:
            return None
        proc = subprocess.run(
            [
                "kubectl",
                "get",
                "taskrun",
                "-n",
                namespace,
                taskrun_name,
                "-o",
                "jsonpath={.metadata.labels.tekton\\.dev/pipelineRun}",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return None
        return proc.stdout.strip()

    def _restart_pod(self, namespace: str, name: str) -> bool:
        proc = subprocess.run(
            ["kubectl", "delete", "pod", "-n", namespace, name, "--wait=false"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        ok = proc.returncode == 0
        if ok:
            self.logger.info("Restarted pod %s/%s", namespace, name)
        return ok

    def _delete_stale_replicaset_pod(self, issue: dict[str, Any]) -> bool:
        ns = issue.get("namespace", "")
        rs_name = issue.get("owner_name")
        if not ns or not rs_name:
            return False

        proc = subprocess.run(
            ["kubectl", "get", "rs", "-n", ns, "-o", "json"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if proc.returncode != 0:
            return False
        try:
            items = json.loads(proc.stdout).get("items", [])
        except JSONDecodeError:
            return False

        same_deploy: list[tuple[str, datetime]] = []
        target_owner = None
        for rs in items:
            meta = rs.get("metadata", {})
            if meta.get("name") == rs_name:
                for ref in meta.get("ownerReferences") or []:
                    if ref.get("kind") == "Deployment":
                        target_owner = ref.get("name")
                        break
            if target_owner:
                for ref in meta.get("ownerReferences") or []:
                    if (
                        ref.get("kind") == "Deployment"
                        and ref.get("name") == target_owner
                    ):
                        created = meta.get("creationTimestamp")
                        if created:
                            same_deploy.append(
                                (
                                    meta.get("name", ""),
                                    datetime.fromisoformat(
                                        created.replace("Z", "+00:00")
                                    ),
                                )
                            )

        if len(same_deploy) < 2:
            return False

        same_deploy.sort(key=lambda x: x[1], reverse=True)
        newest = same_deploy[0][0]
        if rs_name == newest:
            return False

        return self._restart_pod(ns, issue.get("name", ""))
