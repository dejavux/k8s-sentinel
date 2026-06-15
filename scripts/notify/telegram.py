"""Optional Telegram summary after Sentinel check/fix runs."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from checks.base import CheckResult, FixResult

logger = logging.getLogger(__name__)


def telegram_notify_enabled() -> bool:
    return os.getenv("SENTINEL_TELEGRAM_NOTIFY", "false").lower() == "true"


def _telegram_credentials() -> tuple[str, str] | None:
    token = (
        os.getenv("SENTINEL_TELEGRAM_BOT_TOKEN")
        or os.getenv("TELEGRAM_BOT_TOKEN")
        or ""
    ).strip()
    chat_id = (
        os.getenv("SENTINEL_TELEGRAM_CHAT_ID")
        or os.getenv("TELEGRAM_CHAT_ID")
        or ""
    ).strip()
    if token and chat_id:
        return token, chat_id
    return None


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _module_lines(check_results: dict[str, CheckResult]) -> list[str]:
    lines: list[str] = []
    for name in sorted(check_results):
        result = check_results[name]
        icon = {"ok": "✅", "warning": "⚠️", "error": "❌"}.get(result.status, "•")
        lines.append(f"{icon} <b>{_escape_html(name)}</b>: {_escape_html(result.message)}")
    return lines


def _fix_lines(fix_results: dict[str, FixResult] | None) -> list[str]:
    if not fix_results:
        return []
    lines: list[str] = []
    for name in sorted(fix_results):
        fix = fix_results[name]
        icon = "✅" if fix.success else "❌"
        lines.append(f"{icon} <b>{_escape_html(name)}</b>: {_escape_html(fix.message)}")
    return lines


def build_summary_message(
    check_results: dict[str, CheckResult],
    fix_results: dict[str, FixResult] | None,
    *,
    pr_result: dict[str, Any] | None = None,
) -> str:
    """Build HTML message for Telegram."""
    errors = sum(1 for r in check_results.values() if r.status == "error")
    warnings = sum(1 for r in check_results.values() if r.status == "warning")
    if errors:
        headline = "❌ K8s Sentinel — errors remain"
    elif warnings:
        headline = "⚠️ K8s Sentinel — warnings"
    elif fix_results:
        headline = "✅ K8s Sentinel — auto-fix complete"
    else:
        headline = "✅ K8s Sentinel — all healthy"

    parts = [f"<b>{headline}</b>"]
    module_lines = _module_lines(check_results)
    if module_lines:
        parts.append("")
        parts.append("<b>Checks</b>")
        parts.extend(module_lines)

    fix_lines = _fix_lines(fix_results)
    if fix_lines:
        parts.append("")
        parts.append("<b>Fixes</b>")
        parts.extend(fix_lines)

    if pr_result:
        parts.append("")
        if pr_result.get("success") and pr_result.get("pr_url"):
            parts.append(f"<b>PR</b>: {_escape_html(str(pr_result['pr_url']))}")
            if pr_result.get("merged"):
                parts.append("Auto-merged: yes")
        elif pr_result.get("message"):
            parts.append(
                f"<b>PR</b>: skipped — {_escape_html(str(pr_result['message']))}"
            )

    return "\n".join(parts)


def should_send_summary(
    check_results: dict[str, CheckResult],
    fix_results: dict[str, FixResult] | None,
    *,
    pr_result: dict[str, Any] | None = None,
) -> bool:
    """Send when fixes ran, a PR was attempted, or checks are not all ok."""
    if fix_results or pr_result:
        return True
    return any(not r.is_healthy() for r in check_results.values())


def send_telegram_message(text: str) -> bool:
    creds = _telegram_credentials()
    if creds is None:
        logger.warning("Telegram notify enabled but bot token or chat id missing")
        return False
    token, chat_id = creds
    payload = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }
    ).encode("utf-8")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    request = urllib.request.Request(url, data=payload, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        logger.warning("Telegram send failed: %s", exc)
        return False
    if not body.get("ok"):
        logger.warning("Telegram API error: %s", body)
        return False
    return True


def maybe_send_telegram_summary(
    check_results: dict[str, CheckResult],
    fix_results: dict[str, FixResult] | None,
    *,
    pr_result: dict[str, Any] | None = None,
) -> None:
    """Post run summary when enabled and the run had actionable output."""
    if not telegram_notify_enabled():
        return
    if not should_send_summary(check_results, fix_results, pr_result=pr_result):
        return
    message = build_summary_message(
        check_results, fix_results, pr_result=pr_result
    )
    if send_telegram_message(message):
        logger.info("Telegram summary sent")
