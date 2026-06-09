"""GitOps: create fix PR from Sentinel results (Cursor SDK + gh)."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from gitops.repo_bootstrap import ensure_clone

logger = logging.getLogger(__name__)

ROOT = Path(os.getenv("SENTINEL_INFRA_ROOT", "/workspace/infra-bootstrap"))

# 低風險路徑：允許 Sentinel bot 自動 approve + merge（高風險 manifest 不在此列）
AUTO_MERGE_PATH_PREFIXES = tuple(
    p.strip()
    for p in os.getenv(
        "SENTINEL_AUTO_MERGE_WHITELIST",
        "60_apps/k8s-sentinel/,"
        "60_apps/buildkit/,"
        "60_apps/docker-registry/,"
        "60_apps/tekton-ci/scripts/prune-ci-node-ephemeral.sh,"
        "00_docs/operations/runbooks/,"
        "40_k8s/playbooks/maintenance/,"
        "40_k8s/roles/13_gpu_support/tasks/ensure_runc.yml,"
        "70_monitoring/manifests/",
    ).split(",")
    if p.strip()
)

_BRANCH_PREFIX = "sentinel/fix-"


def count_open_sentinel_prs(repo_root: Path) -> int:
    """Count open PRs whose head branch starts with sentinel/fix-."""
    proc = gh_cmd(
        repo_root,
        [
            "pr",
            "list",
            "--state",
            "open",
            "--json",
            "headRefName",
            "--limit",
            "50",
        ],
    )
    if proc.returncode != 0:
        logger.warning("gh pr list failed: %s", proc.stderr[-300:])
        return 0
    try:
        items = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return 0
    return sum(
        1
        for item in items
        if str(item.get("headRefName", "")).startswith(_BRANCH_PREFIX)
    )


def open_sentinel_pr_limit_reached(repo_root: Path) -> bool:
    """True when open sentinel/fix-* PRs meet or exceed SENTINEL_MAX_OPEN_PRS."""
    limit = int(os.getenv("SENTINEL_MAX_OPEN_PRS", "1"))
    if limit <= 0:
        return False
    open_count = count_open_sentinel_prs(repo_root)
    if open_count >= limit:
        logger.info(
            "Skipping new PR: %d open sentinel PR(s) (limit=%d)",
            open_count,
            limit,
        )
        return True
    return False


def sanitize_git_branch_slug(raw: str, *, prefix: str = _BRANCH_PREFIX) -> str:
    """Build a valid git ref name (no spaces, no repeated slashes)."""
    slug = raw.replace(",", "-").replace(" ", "-")
    slug = re.sub(r"[^a-zA-Z0-9._/-]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-/")
    if not slug:
        slug = "run"
    max_slug = max(1, 200 - len(prefix))
    if len(slug) > max_slug:
        slug = slug[:max_slug].rstrip("-/")
    return f"{prefix}{slug}"


def is_auto_merge_eligible(files: list[dict[str, str]]) -> bool:
    """True when every changed file is under the low-risk whitelist."""
    if not files:
        return False
    for item in files:
        rel = item.get("path", "").lstrip("/")
        if not rel:
            return False
        if not any(
            rel.startswith(prefix.rstrip("/") + "/") or rel == prefix.rstrip("/")
            for prefix in AUTO_MERGE_PATH_PREFIXES
        ):
            logger.info("Auto-merge skipped: %s not in whitelist", rel)
            return False
    return True


def create_fix_pr(
    check_fix_payload: dict[str, Any],
    *,
    repo_root: Path | None = None,
    base_branch: str = "main",
    auto_merge: bool = False,
) -> dict[str, Any]:
    """Create branch, commit fix files, and open a PR via gh."""
    root = repo_root or ensure_clone()
    meta = generate_pr_meta(check_fix_payload, repo_root=root)
    files: list[dict[str, str]] = meta.get("files") or []
    if not files:
        logger.warning("No files to commit; skipping PR")
        return {"success": False, "message": "no files in PR meta"}

    if open_sentinel_pr_limit_reached(root):
        return {
            "success": False,
            "message": "open sentinel PR exists; skip duplicate",
            "open_sentinel_prs": count_open_sentinel_prs(root),
        }

    branch = sanitize_git_branch_slug(
        str(
            meta.get("branch") or check_fix_payload.get("timestamp", "run")
        ).removeprefix(_BRANCH_PREFIX)
    )
    title = meta.get("title") or "fix(sentinel): automated repair"
    body = meta.get("body") or "Automated fix from K8s Sentinel."

    git_cmd(root, ["fetch", "origin", base_branch])
    git_cmd(root, ["checkout", "-B", branch, f"origin/{base_branch}"])

    for item in files:
        rel = item.get("path", "").lstrip("/")
        content = item.get("content", "")
        if not rel:
            continue
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        git_cmd(root, ["add", rel])

    git_cmd(root, ["commit", "-m", title])
    git_cmd(root, ["push", "-u", "origin", branch])

    pr_url = gh_pr_create(root, title, body, base_branch, branch)
    result: dict[str, Any] = {"success": True, "pr_url": pr_url, "branch": branch}

    if auto_merge and pr_url and is_auto_merge_eligible(files):
        approve_and_merge_pr(root, pr_url, result)
    elif auto_merge and pr_url:
        result["auto_merge"] = False
        result["auto_merge_skipped"] = "files outside whitelist"

    return result


def generate_pr_meta(
    payload: dict[str, Any], *, repo_root: Path | None = None
) -> dict[str, Any]:
    """Build PR metadata via Cursor SDK or fallback template."""
    root = repo_root or ROOT
    api_key = os.getenv("CURSOR_API_KEY")
    script = Path("/app/scripts/gitops/cursor_fix_pr.ts")
    if not script.is_file():
        script = root / "60_apps/k8s-sentinel/scripts/gitops/cursor_fix_pr.ts"
    if api_key and script.is_file():
        try:
            proc = subprocess.run(
                ["npx", "--prefix", "/app", "tsx", str(script)],
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                check=False,
                cwd=str(root),
                env={**os.environ, "CURSOR_API_KEY": api_key},
                timeout=300,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return json.loads(proc.stdout.strip())
            logger.warning("Cursor PR meta failed: %s", proc.stderr[-500:])
        except (subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            logger.warning("Cursor PR generation error: %s", exc)

    checks = payload.get("checks", {})
    modules = "-".join(sorted(checks.keys())) if checks else "unknown"
    body = (
        "## Summary\n\n"
        f"Automated Sentinel repair for: {modules}\n\n"
        "## Test plan\n\n"
        "- [ ] Verify cluster health\n"
    )
    return {
        "title": f"fix(sentinel): repair {modules}",
        "body": body,
        "branch": sanitize_git_branch_slug(modules),
        "files": [],
    }


def git_cmd(repo_root: Path, args: list[str]) -> None:
    """Run git in repo_root."""
    subprocess.run(
        ["git", *args],
        cwd=str(repo_root),
        check=True,
        capture_output=True,
        text=True,
    )


def gh_cmd(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run gh in repo_root."""
    return subprocess.run(
        ["gh", *args],
        cwd=str(repo_root),
        check=False,
        capture_output=True,
        text=True,
        env=os.environ,
    )


def approve_and_merge_pr(repo_root: Path, pr_url: str, result: dict[str, Any]) -> None:
    """Auto-review (approve) then squash-merge whitelisted low-risk PRs."""
    review = gh_cmd(
        repo_root,
        [
            "pr",
            "review",
            pr_url,
            "--approve",
            "--body",
            "Auto-approved by K8s Sentinel (low-risk whitelist).",
        ],
    )
    if review.returncode != 0:
        logger.warning("gh pr review failed: %s", review.stderr[-500:])
        result["auto_merge"] = False
        result["auto_merge_error"] = review.stderr.strip() or "review failed"
        return

    merge = gh_cmd(
        repo_root,
        ["pr", "merge", pr_url, "--squash", "--delete-branch", "--admin"],
    )
    if merge.returncode != 0:
        logger.warning("gh pr merge failed: %s", merge.stderr[-500:])
        result["auto_merge"] = False
        result["auto_merge_error"] = merge.stderr.strip() or "merge failed"
        return

    result["auto_merge"] = True
    result["merged"] = True
    logger.info("Auto-merged PR: %s", pr_url)


def gh_pr_create(
    repo_root: Path, title: str, body: str, base: str, head: str
) -> str | None:
    """Create GitHub PR and return URL."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(body)
        body_path = f.name
    try:
        proc = gh_cmd(
            repo_root,
            [
                "pr",
                "create",
                "--title",
                title,
                "--body-file",
                body_path,
                "--base",
                base,
                "--head",
                head,
            ],
        )
        if proc.returncode != 0:
            logger.error("gh pr create failed: %s", proc.stderr)
            return None
        return proc.stdout.strip()
    finally:
        Path(body_path).unlink(missing_ok=True)
