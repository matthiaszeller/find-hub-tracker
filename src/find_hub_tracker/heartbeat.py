"""External ping (Healthchecks.io) + internal DB heartbeat record."""

from __future__ import annotations

import platform

import httpx
import structlog

from find_hub_tracker import __version__
from find_hub_tracker.models import ServiceHeartBeat

log = structlog.get_logger()


async def ping_healthchecks(url: str | None, *, success: bool = True) -> None:
    """Fire-and-forget HTTP GET to Healthchecks.io ping URL.

    Args:
        url: The Healthchecks.io ping URL. If None or empty, silently returns.
        success: If True, ping the success endpoint. If False, ping /fail.
    """
    if not url:
        return

    target = url if success else f"{url.rstrip('/')}/fail"

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(target)
            resp.raise_for_status()

        log.debug("healthchecks_pinged", url=target, status=resp.status_code)

    except Exception:
        log.warning("healthchecks_ping_failed", url=target, exc_info=True)


def make_heartbeat(
    poll_count: int, error_count: int, *, service_name: str = "find-hub-tracker"
) -> ServiceHeartBeat:
    host = platform.node() or "unknown"
    version = __version__

    return ServiceHeartBeat(
        service_name=service_name,
        host=host,
        poll_count=poll_count,
        error_count=error_count,
        version=version,
    )
