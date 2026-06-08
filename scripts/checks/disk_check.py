"""
K8s Sentinel - 節點磁碟 / ephemeral-storage 檢查模組

偵測 DiskPressure、host rootfs 使用率（Ansible df）、ephemeral-storage 壓力，
並可執行叢集內安全清理。
節點 host 層清理對接：
  - 60_apps/tekton-ci/scripts/prune-ci-node-ephemeral.sh
  - 10_baremetal/playbooks/deploy_disk_maintenance.yml
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import subprocess
from json import JSONDecodeError
from typing import Any

from fixers.ansible_runner import AnsibleRunner

from .base import BaseCheck, CheckResult, FixResult

logger = logging.getLogger(__name__)

# Align with 10_baremetal/scripts/system_disk_maintenance.sh (MAX_DISK_USAGE=75)
DEFAULT_DISK_WARN_PERCENT = int(os.getenv("SENTINEL_DISK_WARN_PERCENT", "75"))
DEFAULT_DISK_ERROR_PERCENT = int(os.getenv("SENTINEL_DISK_ERROR_PERCENT", "85"))


class DiskCheck(BaseCheck):
    """節點磁碟與 ephemeral-storage 壓力檢查"""

    @property
    def name(self) -> str:
        return "disk"

    @property
    def description(self) -> str:
        return "檢查節點 DiskPressure / host rootfs 使用率，並清理 CI 已完成 Pod"

    def check(self) -> CheckResult:
        self.logger.info("Starting %s check...", self.name)

        try:
            nodes = self._get_nodes()
            if not nodes:
                return CheckResult(
                    module=self.name,
                    status="error",
                    message="No nodes found",
                )

            host_disk = self._collect_host_disk_usage(
                [node["metadata"]["name"] for node in nodes]
            )

            pressure_nodes: list[str] = []
            error_nodes: list[str] = []
            warn_nodes: list[str] = []
            node_details: dict[str, Any] = {}

            for node in nodes:
                name = node["metadata"]["name"]
                detail = self.analyze_node(node, host_disk.get(name))
                node_details[name] = detail

                if detail.get("disk_pressure") or detail.get("host_disk_error"):
                    pressure_nodes.append(name)
                    if detail.get("host_disk_error") and not detail.get(
                        "disk_pressure"
                    ):
                        error_nodes.append(name)
                elif detail.get("host_disk_warn"):
                    warn_nodes.append(name)

            affected = sorted(set(pressure_nodes + warn_nodes))

            if pressure_nodes:
                msg_parts = [
                    f"DiskPressure/high rootfs on {len(pressure_nodes)} node(s)"
                ]
                if warn_nodes:
                    msg_parts.append(f"{len(warn_nodes)} additional warning(s)")
                return CheckResult(
                    module=self.name,
                    status="error",
                    message="; ".join(msg_parts),
                    details={
                        "pressure_nodes": pressure_nodes,
                        "error_nodes": error_nodes,
                        "warn_nodes": warn_nodes,
                        "nodes": node_details,
                        "host_disk": host_disk,
                        "warn_percent": DEFAULT_DISK_WARN_PERCENT,
                        "error_percent": DEFAULT_DISK_ERROR_PERCENT,
                    },
                    affected_nodes=affected,
                )

            if warn_nodes:
                return CheckResult(
                    module=self.name,
                    status="warning",
                    message=(
                        f"Host rootfs usage high on {len(warn_nodes)} node(s) "
                        f"(>={DEFAULT_DISK_WARN_PERCENT}%)"
                    ),
                    details={
                        "warn_nodes": warn_nodes,
                        "nodes": node_details,
                        "host_disk": host_disk,
                        "warn_percent": DEFAULT_DISK_WARN_PERCENT,
                        "error_percent": DEFAULT_DISK_ERROR_PERCENT,
                    },
                    affected_nodes=affected,
                )

            return CheckResult(
                module=self.name,
                status="ok",
                message=f"Disk/ephemeral healthy on {len(nodes)} node(s)",
                details={"nodes": node_details, "host_disk": host_disk},
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
                message="No disk issues to fix",
                fixed_nodes=[],
                failed_nodes=[],
            )

        details = check_result.details or {}
        pressure_nodes: list[str] = list(details.get("pressure_nodes") or [])
        warn_nodes: list[str] = list(details.get("warn_nodes") or [])
        target_nodes = sorted(
            set(pressure_nodes) or set(check_result.affected_nodes or [])
        )

        self.logger.info("Running stale pod cleanup (all namespaces)...")
        deleted = self._delete_stale_pods()

        ansible_details: dict[str, Any] = {}
        ansible_enabled = os.getenv("SENTINEL_DISK_ANSIBLE", "false").lower() == "true"

        if ansible_enabled and target_nodes:
            ansible_details = self._run_host_disk_remediation(
                target_nodes, pressure_nodes, warn_nodes
            )
        elif target_nodes and pressure_nodes:
            self.logger.warning(
                "DiskPressure on %s but SENTINEL_DISK_ANSIBLE=false; "
                "only cluster stale-pod cleanup ran",
                pressure_nodes,
            )

        post = self.check()
        post_details = post.details or {}
        remaining_pressure: list[str] = list(post_details.get("pressure_nodes") or [])
        remaining_warn: list[str] = list(post_details.get("warn_nodes") or [])

        cleared_pressure = [n for n in pressure_nodes if n not in remaining_pressure]
        failed_nodes = remaining_pressure
        fixed_nodes = sorted(set(cleared_pressure))

        if remaining_pressure:
            success = False
            message = (
                f"DiskPressure/high rootfs persists on {len(remaining_pressure)} "
                f"node(s) after cleanup ({', '.join(remaining_pressure)})"
            )
        elif remaining_warn:
            success = True
            message = (
                f"DiskPressure cleared; rootfs still high on "
                f"{len(remaining_warn)} node(s) (warning only)"
            )
            fixed_nodes = sorted(set(fixed_nodes + remaining_warn))
        else:
            success = True
            message = (
                f"Disk healthy after cleanup "
                f"(deleted {deleted} stale pod(s)"
                f"{'; host prune via Ansible' if ansible_details else ''})"
            )

        return FixResult(
            module=self.name,
            success=success,
            message=message,
            fixed_nodes=fixed_nodes,
            failed_nodes=failed_nodes,
            details={
                "deleted_stale_pods": deleted,
                "pre_pressure_nodes": pressure_nodes,
                "pre_warn_nodes": warn_nodes,
                "post_pressure_nodes": remaining_pressure,
                "post_warn_nodes": remaining_warn,
                "ansible": ansible_details,
                "host_playbooks": [
                    "60_apps/tekton-ci/scripts/prune-ci-node-ephemeral.sh",
                    "10_baremetal/playbooks/deploy_disk_maintenance.yml",
                ],
            },
        )

    def _collect_host_disk_usage(self, node_names: list[str]) -> dict[str, Any]:
        if os.getenv("SENTINEL_DISK_ANSIBLE", "false").lower() != "true":
            return {}
        try:
            return AnsibleRunner().collect_root_disk_usage(node_names)
        except OSError as exc:
            self.logger.warning("Host disk usage collection failed: %s", exc)
            return {"_error": str(exc)}

    def _run_host_disk_remediation(
        self,
        target_nodes: list[str],
        pressure_nodes: list[str],
        warn_nodes: list[str],
    ) -> dict[str, Any]:
        """Clone repo and run Ansible host-level ephemeral / disk cleanup."""
        out: dict[str, Any] = {"target_nodes": target_nodes}
        try:
            ensure_clone = importlib.import_module("gitops.repo_bootstrap").ensure_clone
            ensure_clone()
        except (RuntimeError, subprocess.CalledProcessError, OSError) as exc:
            self.logger.exception("Repo clone for Ansible failed: %s", exc)
            out["clone_error"] = str(exc)
            return out

        runner = AnsibleRunner()

        self.logger.info(
            "Ansible ephemeral prune on %d node(s): %s",
            len(target_nodes),
            ",".join(target_nodes),
        )
        prune_result = runner.prune_ci_node_ephemeral(target_nodes, dry_run=False)
        out["prune"] = {
            "success": prune_result.success,
            "message": prune_result.message,
            "returncode": prune_result.returncode,
        }
        if not prune_result.success:
            self.logger.warning("Ephemeral prune failed: %s", prune_result.message)

        maintenance_targets = sorted(set(pressure_nodes + warn_nodes))
        if maintenance_targets:
            self.logger.info(
                "Ansible disk maintenance on %d node(s): %s",
                len(maintenance_targets),
                ",".join(maintenance_targets),
            )
            maintenance_result = runner.deploy_disk_maintenance(
                limit=maintenance_targets
            )
            out["disk_maintenance"] = {
                "success": maintenance_result.success,
                "message": maintenance_result.message,
                "returncode": maintenance_result.returncode,
                "nodes": maintenance_targets,
            }
            if not maintenance_result.success:
                self.logger.warning(
                    "Disk maintenance playbook failed: %s",
                    maintenance_result.message,
                )

        return out

    def _get_nodes(self) -> list[dict[str, Any]]:
        result = subprocess.run(
            ["kubectl", "get", "nodes", "-o", "json"],
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(result.stdout)
        return data.get("items", [])

    def analyze_node(
        self, node: dict[str, Any], host_disk: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Derive disk pressure and host rootfs thresholds for one node."""
        conditions = {
            c["type"]: c["status"] for c in node.get("status", {}).get("conditions", [])
        }
        disk_pressure = conditions.get("DiskPressure") == "True"

        root_use_percent = None
        host_disk_warn = False
        host_disk_error = False
        if host_disk:
            raw = host_disk.get("root_use_percent")
            if raw is not None:
                root_use_percent = float(raw)
                host_disk_error = root_use_percent >= DEFAULT_DISK_ERROR_PERCENT
                host_disk_warn = (
                    root_use_percent >= DEFAULT_DISK_WARN_PERCENT
                    and not host_disk_error
                )

        return {
            "disk_pressure": disk_pressure,
            "host_disk_warn": host_disk_warn and not disk_pressure,
            "host_disk_error": host_disk_error and not disk_pressure,
            "root_use_percent": root_use_percent,
            "root_size": host_disk.get("root_size") if host_disk else None,
            "root_used": host_disk.get("root_used") if host_disk else None,
            "root_avail": host_disk.get("root_avail") if host_disk else None,
            "roles": node.get("metadata", {}).get("labels", {}),
        }

    def prune_stale_pods(self) -> int:
        """Delete terminal pods cluster-wide (Succeeded / Failed)."""
        return self._delete_stale_pods()

    def _delete_stale_pods(self) -> int:
        deleted = 0
        for phase in ("Succeeded", "Failed"):
            result = subprocess.run(
                [
                    "kubectl",
                    "get",
                    "pods",
                    "-A",
                    f"--field-selector=status.phase={phase}",
                    "-o",
                    "json",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0 or not result.stdout.strip():
                continue
            try:
                data = json.loads(result.stdout)
            except JSONDecodeError:
                continue
            for item in data.get("items", []):
                meta = item.get("metadata", {})
                ns = meta.get("namespace")
                pod = meta.get("name")
                if not ns or not pod:
                    continue
                del_result = subprocess.run(
                    ["kubectl", "delete", "pod", "-n", ns, pod, "--wait=false"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if del_result.returncode == 0:
                    deleted += 1
                    self.logger.info("Deleted %s pod %s/%s", phase.lower(), ns, pod)
        return deleted
