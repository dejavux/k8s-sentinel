"""Enqueue GitOps jobs for delta My Machines / local-runtime consumer."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def gitops_dispatch_mode() -> str:
    """inline = legacy in-pod cloud SDK; queue = delta local consumer."""
    return os.getenv("SENTINEL_GITOPS_DISPATCH", "inline").strip().lower()


def _ssh_base() -> list[str]:
    key = os.getenv("SENTINEL_GITOPS_SSH_KEY", "/root/.ssh/id_rsa")
    user = os.getenv("SENTINEL_GITOPS_QUEUE_USER", "light0")
    host = os.getenv("SENTINEL_GITOPS_QUEUE_HOST", "192.168.50.110")
    return [
        "ssh",
        "-i",
        key,
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "IdentitiesOnly=yes",
        f"{user}@{host}",
    ]


def _scp_base() -> list[str]:
    key = os.getenv("SENTINEL_GITOPS_SSH_KEY", "/root/.ssh/id_rsa")
    return [
        "scp",
        "-i",
        key,
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "IdentitiesOnly=yes",
    ]


def enqueue_gitops_job(payload: dict[str, Any]) -> dict[str, Any]:
    """Write payload JSON to delta queue directory via SSH/SCP."""
    queue_dir = os.getenv(
        "SENTINEL_GITOPS_QUEUE_DIR",
        "/mnt/volume1/nfs-models/sentinel-gitops/pending",
    )
    job_id = str(payload.get("timestamp", "run")).replace(":", "-")
    remote_path = f"{queue_dir}/{job_id}.json"

    mkdir = subprocess.run(
        [*_ssh_base(), f"mkdir -p {queue_dir}"],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if mkdir.returncode != 0:
        logger.error("queue mkdir failed: %s", mkdir.stderr[-500:])
        return {"success": False, "message": mkdir.stderr.strip() or "mkdir failed"}

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as handle:
        json.dump(payload, handle, indent=2)
        local_path = handle.name

    try:
        proc = subprocess.run(
            [*_scp_base(), local_path, f"{_ssh_base()[-1]}:{remote_path}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    finally:
        Path(local_path).unlink(missing_ok=True)

    if proc.returncode != 0:
        logger.error("queue scp failed: %s", proc.stderr[-500:])
        return {"success": False, "message": proc.stderr.strip() or "scp failed"}

    logger.info("Enqueued GitOps job at %s", remote_path)
    return {
        "success": True,
        "queued": True,
        "remote_path": remote_path,
        "dispatch": "queue",
    }
