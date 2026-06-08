"""Run Ansible playbooks / ad-hoc from Sentinel (Phase 3)."""

from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

INFRA_ROOT = Path(os.getenv("SENTINEL_INFRA_ROOT", "/workspace/infra-bootstrap"))
PACKAGE_ROOT = Path(
    os.getenv(
        "SENTINEL_PACKAGE_ROOT",
        str(INFRA_ROOT / "60_apps/k8s-sentinel"),
    )
)


@dataclass
class AnsibleResult:
    """Result of an Ansible playbook or ad-hoc command."""

    success: bool
    message: str
    playbook: str
    returncode: int
    stdout: str = ""
    stderr: str = ""


class AnsibleRunner:
    """Execute Ansible against baremetal / worker inventory."""

    def __init__(self, infra_root: Path | None = None):
        self.infra_root = infra_root or INFRA_ROOT
        _ensure_ansible_ssh_key()

    def run_playbook(
        self,
        playbook: str,
        *,
        limit: list[str] | None = None,
        extra_vars: dict | None = None,
        dry_run: bool = False,
    ) -> AnsibleResult:
        """Run ansible-playbook relative to infra root."""
        pb_path = self.infra_root / playbook
        if not pb_path.is_file():
            return AnsibleResult(
                success=False,
                message=f"Playbook not found: {pb_path}",
                playbook=playbook,
                returncode=127,
            )

        inventory = os.getenv(
            "ANSIBLE_INVENTORY",
            str(self.infra_root / "40_k8s/inventory/hosts.yml"),
        )
        cmd = [
            "ansible-playbook",
            "-i",
            inventory,
            str(pb_path),
        ]
        if limit:
            cmd.extend(["--limit", ",".join(limit)])
        if extra_vars:
            cmd.extend(["--extra-vars", json.dumps(extra_vars)])
        if dry_run:
            cmd.append("--check")

        logger.info("Running: %s", " ".join(cmd))
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=int(os.getenv("SENTINEL_ANSIBLE_TIMEOUT", "600")),
                env=_ansible_env(),
            )
            ok = proc.returncode == 0
            return AnsibleResult(
                success=ok,
                message="Ansible succeeded"
                if ok
                else f"Ansible failed (rc={proc.returncode})",
                playbook=playbook,
                returncode=proc.returncode,
                stdout=proc.stdout[-4000:],
                stderr=proc.stderr[-2000:],
            )
        except subprocess.TimeoutExpired:
            return AnsibleResult(
                success=False,
                message="Ansible timed out",
                playbook=playbook,
                returncode=124,
            )

    def prune_ci_node_ephemeral(
        self, nodes: list[str], dry_run: bool = False
    ) -> AnsibleResult:
        """Run prune-ci-node-ephemeral.sh on workers via ansible script module."""
        script = (
            self.infra_root / "60_apps/tekton-ci/scripts/prune-ci-node-ephemeral.sh"
        )
        if not script.is_file():
            return AnsibleResult(
                success=False,
                message=f"Script not found: {script}",
                playbook=str(script),
                returncode=127,
            )

        inventory = os.getenv(
            "ANSIBLE_INVENTORY",
            str(self.infra_root / "40_k8s/inventory/hosts.yml"),
        )
        flag = "--dry-run" if dry_run else ""
        cmd = [
            "ansible",
            "-i",
            inventory,
            "k8s_cluster",
            "-m",
            "script",
            "-a",
            f"{script} {flag}".strip(),
            "--become",
        ]
        if nodes:
            cmd.extend(["--limit", ",".join(nodes)])

        logger.info("Running: %s", " ".join(cmd))
        proc = subprocess.run(
            cmd, capture_output=True, text=True, check=False, env=_ansible_env()
        )
        ok = proc.returncode == 0
        return AnsibleResult(
            success=ok,
            message="Ephemeral prune succeeded"
            if ok
            else f"Ephemeral prune failed (rc={proc.returncode})",
            playbook=str(script),
            returncode=proc.returncode,
            stdout=proc.stdout[-4000:],
            stderr=proc.stderr[-2000:],
        )

    def deploy_disk_maintenance(self, limit: list[str] | None = None) -> AnsibleResult:
        """Deploy baremetal disk maintenance cron via Ansible."""
        return self.run_playbook(
            "10_baremetal/playbooks/deploy_disk_maintenance.yml",
            limit=limit,
            extra_vars={"run_disk_cleanup_now": True},
        )

    def fix_containerd_cri(self, limit: list[str] | None = None) -> AnsibleResult:
        """Repair containerd CRI (certs.d + remove mirrors conflict)."""
        playbook = _resolve_sentinel_playbook("fix-containerd-cri.yml")
        return self._run_playbook_path(
            playbook,
            limit=limit,
            extra_vars={
                "target_hosts": ",".join(limit) if limit else "k8s_cluster",
                "registry_endpoint": os.getenv(
                    "SENTINEL_REGISTRY_ENDPOINT", "10.101.22.227:5000"
                ),
                "registry_svc_host": os.getenv(
                    "SENTINEL_REGISTRY_SVC_HOST",
                    "registry.docker-registry-internal.svc.cluster.local:5000",
                ),
            },
        )

    def restart_systemd_service(
        self, service: str, limit: list[str] | None = None
    ) -> AnsibleResult:
        """Restart a systemd unit on k8s nodes via ansible shell."""
        inventory = os.getenv(
            "ANSIBLE_INVENTORY",
            str(self.infra_root / "40_k8s/inventory/hosts.yml"),
        )
        cmd = [
            "ansible",
            "-i",
            inventory,
            "k8s_cluster",
            "-m",
            "systemd",
            "-a",
            f"name={service} state=restarted",
            "--become",
        ]
        if limit:
            cmd.extend(["--limit", ",".join(limit)])
        logger.info("Running: %s", " ".join(cmd))
        proc = subprocess.run(
            cmd, capture_output=True, text=True, check=False, env=_ansible_env()
        )
        ok = proc.returncode == 0
        return AnsibleResult(
            success=ok,
            message=f"{service} restart succeeded"
            if ok
            else f"{service} restart failed (rc={proc.returncode})",
            playbook=service,
            returncode=proc.returncode,
            stdout=proc.stdout[-4000:],
            stderr=proc.stderr[-2000:],
        )

    def probe_systemd(
        self, service: str, nodes: list[str] | None = None
    ) -> dict[str, str]:
        """Return host -> systemd is-active state."""
        inventory = os.getenv(
            "ANSIBLE_INVENTORY",
            str(self.infra_root / "40_k8s/inventory/hosts.yml"),
        )
        cmd = [
            "ansible",
            "-i",
            inventory,
            "k8s_cluster",
            "-m",
            "command",
            "-a",
            f"systemctl is-active {service}",
            "-o",
        ]
        if nodes:
            cmd.extend(["--limit", ",".join(nodes)])
        proc = subprocess.run(
            cmd, capture_output=True, text=True, check=False, env=_ansible_env()
        )
        out: dict[str, str] = {}
        for line in proc.stdout.splitlines():
            host, state = _parse_ansible_command_line(line)
            if host and state:
                out[host] = state
        return out

    def probe_crictl(self, nodes: list[str] | None = None) -> dict[str, str]:
        """Return host -> error snippet when crictl info fails."""
        inventory = os.getenv(
            "ANSIBLE_INVENTORY",
            str(self.infra_root / "40_k8s/inventory/hosts.yml"),
        )
        cmd = [
            "ansible",
            "-i",
            inventory,
            "k8s_cluster",
            "-m",
            "shell",
            "-a",
            "crictl info >/dev/null 2>&1 || crictl info 2>&1 | tail -1",
            "-o",
            "--become",
        ]
        if nodes:
            cmd.extend(["--limit", ",".join(nodes)])
        proc = subprocess.run(
            cmd, capture_output=True, text=True, check=False, env=_ansible_env()
        )
        errors: dict[str, str] = {}
        for line in proc.stdout.splitlines():
            host, msg = _parse_ansible_shell_msg(line)
            if host and msg and "SUCCESS" not in msg:
                errors[host] = msg
        return errors

    def uncordon_nodes(self, nodes: list[str]) -> AnsibleResult:
        """Uncordon nodes after repair (kubectl, not Ansible)."""
        if not nodes:
            return AnsibleResult(
                success=True,
                message="no nodes to uncordon",
                playbook="kubectl uncordon",
                returncode=0,
            )
        cmd = ["kubectl", "uncordon", *nodes]
        logger.info("Running: %s", " ".join(cmd))
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        ok = proc.returncode == 0
        return AnsibleResult(
            success=ok,
            message="uncordoned" if ok else f"uncordon failed (rc={proc.returncode})",
            playbook="kubectl uncordon",
            returncode=proc.returncode,
            stdout=proc.stdout[-2000:],
            stderr=proc.stderr[-1000:],
        )

    def _run_playbook_path(
        self,
        pb_path: Path,
        *,
        limit: list[str] | None = None,
        extra_vars: dict | None = None,
    ) -> AnsibleResult:
        """Run ansible-playbook with absolute playbook path."""
        if not pb_path.is_file():
            return AnsibleResult(
                success=False,
                message=f"Playbook not found: {pb_path}",
                playbook=str(pb_path),
                returncode=127,
            )
        inventory = os.getenv(
            "ANSIBLE_INVENTORY",
            str(self.infra_root / "40_k8s/inventory/hosts.yml"),
        )
        cmd = ["ansible-playbook", "-i", inventory, str(pb_path)]
        if limit:
            cmd.extend(["--limit", ",".join(limit)])
        if extra_vars:
            cmd.extend(["--extra-vars", json.dumps(extra_vars)])
        logger.info("Running: %s", " ".join(cmd))
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=int(os.getenv("SENTINEL_ANSIBLE_TIMEOUT", "600")),
                env=_ansible_env(),
            )
            ok = proc.returncode == 0
            return AnsibleResult(
                success=ok,
                message="Ansible succeeded"
                if ok
                else f"Ansible failed (rc={proc.returncode})",
                playbook=str(pb_path),
                returncode=proc.returncode,
                stdout=proc.stdout[-4000:],
                stderr=proc.stderr[-2000:],
            )
        except subprocess.TimeoutExpired:
            return AnsibleResult(
                success=False,
                message="Ansible timed out",
                playbook=str(pb_path),
                returncode=124,
            )

    def collect_root_disk_usage(
        self, nodes: list[str] | None = None
    ) -> dict[str, dict[str, Any] | str]:
        """Return host root filesystem usage via Ansible (df /)."""
        inventory = os.getenv(
            "ANSIBLE_INVENTORY",
            str(self.infra_root / "40_k8s/inventory/hosts.yml"),
        )
        # One line per host: root_use_percent=79 root_size=48G root_used=35G root_avail=9.4G
        shell_cmd = (
            'df -P / 2>/dev/null | awk \'NR==2 {gsub(/%/,""); '
            'print "root_use_percent=" $5 '
            '" root_size=" $2 " root_used=" $3 " root_avail=" $4}\''
        )
        cmd = [
            "ansible",
            "-i",
            inventory,
            "k8s_cluster",
            "-m",
            "shell",
            "-a",
            shell_cmd,
            "-o",
        ]
        if nodes:
            cmd.extend(["--limit", ",".join(nodes)])

        logger.info("Collecting host disk usage: %s", " ".join(cmd))
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=int(os.getenv("SENTINEL_ANSIBLE_TIMEOUT", "600")),
                env=_ansible_env(),
            )
        except subprocess.TimeoutExpired:
            logger.warning("Host disk usage collection timed out")
            return {"_error": "timeout"}

        parsed: dict[str, dict[str, Any] | str] = {}
        for line in proc.stdout.splitlines():
            host, stats = _parse_ansible_shell_line(line)
            if not host or not stats:
                continue
            parsed[host] = stats

        host_entries = {k: v for k, v in parsed.items() if not k.startswith("_")}
        if proc.returncode != 0 and not host_entries:
            logger.warning(
                "Host disk usage collection failed (rc=%s): %s",
                proc.returncode,
                proc.stderr[-500:],
            )
            parsed["_error"] = f"ansible rc={proc.returncode}"
        elif proc.returncode != 0:
            logger.warning(
                "Host disk usage partial (rc=%s, ok=%d): %s",
                proc.returncode,
                len(host_entries),
                proc.stderr[-300:],
            )
            parsed["_partial"] = f"ansible rc={proc.returncode}"
        return parsed


def _resolve_sentinel_playbook(name: str) -> Path:
    """Resolve playbook under package ansible/playbooks (standalone or monorepo)."""
    custom = os.getenv("SENTINEL_PLAYBOOKS_DIR")
    if custom:
        return Path(custom) / name
    return PACKAGE_ROOT / "ansible" / "playbooks" / name


def _parse_ansible_command_line(line: str) -> tuple[str | None, str | None]:
    """Parse `host | SUCCESS | rc=0 | ...` for command module."""
    if " | " not in line:
        return None, None
    host = line.split(" | ", 1)[0].strip()
    if not host or host.startswith("{"):
        return None, None
    if "FAILED" in line or "UNREACHABLE" in line:
        return host, "failed"
    if "(stdout)" in line:
        state = line.split("(stdout)", 1)[1].strip().split()[0]
        return host, state
    return host, None


def _parse_ansible_shell_msg(line: str) -> tuple[str | None, str | None]:
    """Parse ansible shell one-liner stdout message."""
    if " | " not in line:
        return None, None
    host = line.split(" | ", 1)[0].strip()
    if "FAILED" in line or "UNREACHABLE" in line:
        tail = line.split(" | ", 3)[-1] if line.count(" | ") >= 3 else line
        return host, tail.strip()
    if "(stdout)" in line:
        return host, line.split("(stdout)", 1)[1].strip()
    return host, None


def _parse_ansible_shell_line(line: str) -> tuple[str | None, dict[str, Any] | None]:
    """Parse `worker4 | SUCCESS | rc=0 | (stdout) root_use_percent=79 ...`."""
    if " | " not in line or "(stdout)" not in line:
        return None, None
    host = line.split(" | ", 1)[0].strip()
    if not host or host.startswith("{"):
        return None, None
    stdout = line.split("(stdout)", 1)[1].strip()
    stats: dict[str, Any] = {}
    for token in stdout.split():
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        if key == "root_use_percent":
            try:
                stats["root_use_percent"] = float(value)
            except ValueError:
                continue
        else:
            stats[key] = value
    if "root_use_percent" not in stats:
        return host, None
    return host, stats


def _ensure_ansible_ssh_key() -> None:
    """Pick private key under /root/.ssh when ANSIBLE_PRIVATE_KEY_FILE unset."""
    if os.getenv("ANSIBLE_PRIVATE_KEY_FILE"):
        return
    ssh_dir = Path("/root/.ssh")
    for name in ("id_ed25519", "id_rsa"):
        candidate = ssh_dir / name
        if candidate.is_file():
            os.environ["ANSIBLE_PRIVATE_KEY_FILE"] = str(candidate)
            logger.info("Using Ansible SSH key: %s", candidate)
            return


def _ansible_env() -> dict[str, str]:
    """Ansible subprocess env (no 1Password agent in-cluster)."""
    env = {**os.environ}
    env.setdefault("ANSIBLE_HOST_KEY_CHECKING", "False")
    env.setdefault("ANSIBLE_REMOTE_USER", "light0")
    env.setdefault(
        "ANSIBLE_SSH_ARGS",
        "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
        "-o IdentitiesOnly=yes",
    )
    _ensure_ansible_ssh_key()
    return env
