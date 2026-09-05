#!/usr/bin/env python3
"""Process queued Sentinel GitOps jobs on delta (local Cursor runtime + kubectl)."""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

# Allow running from infra-bootstrap checkout.
_PKG_ROOT = Path(__file__).resolve().parents[1]
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from gitops.pr_creator import create_fix_pr  # noqa: E402
from gitops.repo_bootstrap import ensure_clone  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("sentinel-gitops-consumer")


def _queue_root() -> Path:
    return Path(
        os.getenv(
            "SENTINEL_GITOPS_QUEUE_DIR",
            "/mnt/volume1/nfs-models/sentinel-gitops",
        )
    )


def _process_file(path: Path) -> dict[str, Any]:
    processing = path.parent / "processing" / path.name
    processing.parent.mkdir(parents=True, exist_ok=True)
    path.rename(processing)

    payload = json.loads(processing.read_text(encoding="utf-8"))
    os.environ.setdefault("CURSOR_AGENT_RUNTIME", "local")
    infra_root = os.getenv(
        "SENTINEL_INFRA_ROOT",
        str(Path.home() / "workspace" / "infra-bootstrap"),
    )
    os.environ.setdefault("SENTINEL_INFRA_ROOT", infra_root)
    os.environ.setdefault("SENTINEL_PACKAGE_ROOT", f"{infra_root}/60_apps/k8s-sentinel")

    ensure_clone(Path(infra_root))
    auto_merge = os.getenv("SENTINEL_AUTO_MERGE", "false").lower() == "true"
    result = create_fix_pr(payload, auto_merge=auto_merge, repo_root=Path(infra_root))
    return result


def run_once() -> int:
    pending = _queue_root() / "pending"
    done = _queue_root() / "done"
    failed = _queue_root() / "failed"
    for sub in (pending, done, failed):
        sub.mkdir(parents=True, exist_ok=True)

    jobs = sorted(pending.glob("*.json"))
    if not jobs:
        logger.info("No pending GitOps jobs")
        return 0

    processed = 0
    for job in jobs:
        logger.info("Processing %s", job.name)
        try:
            result = _process_file(job)
            target_dir = done if result.get("success") else failed
            leftover = _queue_root() / "processing" / job.name
            if leftover.exists():
                leftover.rename(target_dir / job.name)
            meta_path = target_dir / f"{job.stem}.result.json"
            meta_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
            processed += 1
            logger.info("Job %s -> %s", job.name, result.get("message", result))
        except (OSError, json.JSONDecodeError, RuntimeError) as exc:
            logger.exception("Job %s failed: %s", job.name, exc)
            processing = _queue_root() / "processing" / job.name
            if processing.exists():
                processing.rename(failed / job.name)

    return 0 if processed >= 0 else 1


def main() -> int:
    return run_once()


if __name__ == "__main__":
    raise SystemExit(main())
