"""Clone or refresh infra-bootstrap before GitOps PR operations."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_ROOT = Path(os.getenv("SENTINEL_INFRA_ROOT", "/workspace/repo"))
DEFAULT_REPO = os.getenv("SENTINEL_GITHUB_REPO", "").strip()
DEFAULT_BRANCH = os.getenv("SENTINEL_GITHUB_BASE", "main")


def ensure_clone(
    *,
    repo_root: Path | None = None,
    repo: str | None = None,
    branch: str | None = None,
) -> Path:
    """Ensure infra-bootstrap exists at repo_root with origin configured."""
    root = repo_root or DEFAULT_ROOT
    gh_repo = (repo or DEFAULT_REPO).strip()
    if not gh_repo:
        raise RuntimeError("SENTINEL_GITHUB_REPO is required for GitOps clone")
    base_branch = branch or DEFAULT_BRANCH
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")

    if (root / ".git").is_dir():
        _git(root, ["fetch", "origin", base_branch])
        _git(root, ["checkout", base_branch])
        _git(root, ["reset", "--hard", f"origin/{base_branch}"])
        logger.info("Refreshed existing clone at %s", root)
        return root

    if not token:
        raise RuntimeError("GITHUB_TOKEN required to clone infra-bootstrap")

    root.parent.mkdir(parents=True, exist_ok=True)
    clone_url = f"https://x-access-token:{token}@github.com/{gh_repo}.git"
    if root.exists() and not any(root.iterdir()):
        root.rmdir()

    _git(
        Path(root.parent), ["clone", "--branch", base_branch, clone_url, str(root.name)]
    )
    logger.info("Cloned %s into %s", gh_repo, root)
    return root


def _git(cwd: Path, args: list[str]) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )
