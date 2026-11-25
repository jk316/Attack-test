"""Experiment monitor lifecycle orchestration.

Single owner for starting/stopping the background RTT (ping) and HTTP
monitors. Both experiment entry points (CLI ``src/main.py`` and the web
console ``backend/experiment.py``) call this module, so the monitor
lifecycle never depends on the agent remembering to call tools.

Startup failures are downgraded to warnings — monitoring must never block
an experiment (spec 009 FR-008). No targets or parameters are hardcoded
here (FR-010): callers pass the effective target IP and the ``http``
section of the runtime config.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from src.tools.http_monitor import get_http_monitor
from src.tools.ping_monitor import get_ping_monitor
from src.tools.ping_rtt_tool import validate_target

logger = logging.getLogger("agent")


def start_experiment_monitors(
    target_ip: str, http_cfg: Optional[dict[str, Any]] = None
) -> dict[str, bool]:
    """Start the background ping monitor, plus the HTTP monitor when configured.

    ``target_ip`` must pass the allowlist (``validate_target``). ``http_cfg``
    is the ``http`` section of the runtime config; the HTTP monitor is only
    started when ``url`` is non-empty. Returns a summary of what actually
    started; any failure is logged and downgraded.
    """
    result: dict[str, bool] = {"ping": False, "http": False}

    try:
        validate_target(target_ip)
        get_ping_monitor().start(target_ip)
        result["ping"] = True
    except Exception:
        logger.warning(
            "ping monitor failed to start for %s (observation degraded)", target_ip,
            exc_info=True,
        )

    if http_cfg and http_cfg.get("url"):
        try:
            kwargs: dict[str, Any] = {"url": http_cfg["url"]}
            for key in ("interval_s", "timeout_s", "method", "body", "content_type"):
                if key in http_cfg:
                    kwargs[key] = http_cfg[key]
            get_http_monitor().start(**kwargs)
            result["http"] = True
        except Exception:
            logger.warning(
                "HTTP monitor failed to start for %s (observation degraded)",
                http_cfg.get("url"),
                exc_info=True,
            )

    return result


def stop_experiment_monitors() -> None:
    """Stop both monitors; safe when either is not running or missing."""
    for getter, name in ((get_ping_monitor, "ping"), (get_http_monitor, "HTTP")):
        try:
            monitor = getter()
            if monitor.is_running():
                monitor.stop()
        except Exception:
            logger.warning("%s monitor stop failed", name, exc_info=True)
