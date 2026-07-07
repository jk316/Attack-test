"""
Centralised logging and configuration for the Pktgen Agent.

Replaces the ad-hoc print() calls scattered across agent.py with
proper structured logging that integrates with LangChain V1.0's
callback and tracing infrastructure.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# ── Logging setup ──


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure the root logger for Pktgen Agent.

    Args:
        level: Logging level (default: INFO).

    Returns:
        The configured root logger.
    """
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt = "%H:%M:%S"

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(fmt, datefmt=datefmt))

    root = logging.getLogger("pktgen_agent")
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)
    root.propagate = False

    return root


# ── .env loading (single implementation) ──


def load_dotenv(env_path: Path | None = None) -> None:
    """Load environment variables from .env file.

    Uses python-dotenv if available; otherwise falls back to a simple
    manual parser that handles basic KEY=VALUE lines.

    Args:
        env_path: Path to .env file (default: <project_root>/.env).
    """
    if env_path is None:
        env_path = Path(__file__).resolve().parent.parent / ".env"

    if not env_path.exists():
        return

    try:
        from dotenv import load_dotenv as _load

        _load(env_path)
    except ImportError:
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key not in os.environ:
                    os.environ[key] = value


def require_env(var_name: str) -> str:
    """Get a required environment variable, raising if missing.

    Args:
        var_name: Environment variable name.

    Returns:
        The value.

    Raises:
        RuntimeError: If the variable is not set.
    """
    value = os.environ.get(var_name)
    if not value:
        raise RuntimeError(
            f"Required environment variable '{var_name}' is not set. "
            f"Add it to your .env file or environment."
        )
    return value
