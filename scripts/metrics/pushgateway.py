"""Push Prometheus text metrics to Pushgateway (for CronJob / batch jobs)."""

from __future__ import annotations

import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)


def push_prometheus_metrics(
    pushgateway_url: str,
    job: str,
    text: str,
    *,
    timeout_sec: float = 15.0,
) -> None:
    """PUT metrics to Pushgateway job endpoint."""
    base = pushgateway_url.rstrip("/")
    push_url = f"{base}/metrics/job/{job}"
    request = urllib.request.Request(
        push_url,
        data=text.encode("utf-8"),
        method="PUT",
        headers={"Content-Type": "text/plain; version=0.0.4; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            if response.status >= 400:
                raise urllib.error.HTTPError(
                    push_url,
                    response.status,
                    response.reason,
                    response.headers,
                    None,
                )
    except urllib.error.URLError as exc:
        logger.warning("Pushgateway push failed: %s", exc)
        raise
