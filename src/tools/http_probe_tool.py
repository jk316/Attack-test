"""HTTP Probe Tool - active dial-testing of an HTTP business endpoint via curl.

Provides single-shot HTTP probing with per-phase timing (DNS / TCP / TLS /
TTFB / total), HTTP status code, download size/speed, and error classification,
gated by the same allowlist used for traffic tools.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
from typing import Any, Optional
from urllib.parse import urlparse

from src.tools.ping_rtt_tool import is_valid_ip, validate_target

# curl exit codes → error classification
_CURLE_COULDNT_RESOLVE_HOST = 6
_CURLE_COULDNT_CONNECT = 7
_CURLE_OPERATION_TIMEDOUT = 28
_CURLE_SSL_CONNECT_ERROR = 35
_CURLE_SSL_CERTPROBLEM = 60

_CURL_WRITE_FORMAT = (
    "%{time_namelookup}|%{time_connect}|%{time_appconnect}|"
    "%{time_starttransfer}|%{time_total}|%{http_code}|"
    "%{size_download}|%{speed_download}"
)


def _curl_available() -> bool:
    """Return True if the curl binary is on PATH."""
    return shutil.which("curl") is not None


def validate_http_url(url: str) -> str:
    """Validate a URL's host against the allowlist; return the resolved host IP.

    Accepts http/https URLs only. If the host is already an IP it is validated
    directly; if it is a domain name it is resolved to an IP first. Raises
    ``ValueError`` on any violation.
    """
    if not url or not isinstance(url, str):
        raise ValueError("url must be a non-empty string")

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"unsupported scheme: {parsed.scheme!r} (only http/https)")

    host = parsed.hostname
    if not host:
        raise ValueError(f"url has no host: {url!r}")

    if is_valid_ip(host):
        validate_target(host)
        return host

    try:
        ip = socket.gethostbyname(host)
    except OSError as e:
        raise ValueError(f"failed to resolve host {host!r}: {e}")

    validate_target(ip)
    return ip


def _classify_error(returncode: int) -> Optional[str]:
    """Map a curl exit code to a human-readable error type (None on success)."""
    if returncode == 0:
        return None
    mapping = {
        _CURLE_COULDNT_RESOLVE_HOST: "dns_error",
        _CURLE_COULDNT_CONNECT: "connection_refused",
        _CURLE_OPERATION_TIMEDOUT: "timeout",
        _CURLE_SSL_CONNECT_ERROR: "tls_error",
        _CURLE_SSL_CERTPROBLEM: "tls_error",
    }
    return mapping.get(returncode, "other")


def _run_curl(url: str, method: str = "GET", timeout_s: float = 5.0) -> dict[str, Any]:
    """Run a single curl request and parse timing / status / size metrics."""
    if not _curl_available():
        return {
            "success": False,
            "error_type": "curl_missing",
            "raw_error": "curl binary not found on PATH",
        }

    cmd = [
        "curl", "-s", "-o", "/dev/null",
        "--max-time", str(int(timeout_s)),
        "-X", method,
        "-w", _CURL_WRITE_FORMAT,
        url,
    ]

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_s + 5,
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "error_type": "timeout", "raw_error": "curl subprocess timed out"}
    except FileNotFoundError:
        return {"success": False, "error_type": "curl_missing", "raw_error": "curl binary not found"}

    parts = (proc.stdout or "").strip().split("|")
    error_type = _classify_error(proc.returncode) if proc.returncode != 0 else None

    def _ms(value: str) -> Optional[float]:
        try:
            return round(float(value) * 1000, 3)
        except (ValueError, TypeError):
            return None

    result: dict[str, Any] = {
        "success": proc.returncode == 0,
        "error_type": error_type,
        "raw_error": (proc.stderr or "").strip()[:300] or None,
    }

    if len(parts) >= 8:
        result["dns_ms"] = _ms(parts[0])
        result["tcp_connect_ms"] = _ms(parts[1])
        result["tls_ms"] = _ms(parts[2])
        result["ttfb_ms"] = _ms(parts[3])
        result["total_ms"] = _ms(parts[4])
        try:
            result["status_code"] = int(parts[5]) if parts[5] != "000" else None
        except ValueError:
            result["status_code"] = None
        try:
            result["size_bytes"] = int(float(parts[6]))
        except ValueError:
            result["size_bytes"] = None
        try:
            result["speed_bps"] = round(float(parts[7]), 1)
        except ValueError:
            result["speed_bps"] = None

    return result


def http_probe(url: str, method: str = "GET", timeout_s: float = 5.0) -> dict[str, Any]:
    """Probe an HTTP endpoint (allowlist-gated) and return timing/status metrics.

    Args:
        url: Full http/https URL to probe (host must be allowlisted).
        method: HTTP method (default "GET").
        timeout_s: Per-request timeout in seconds (default 5).

    Returns:
        Dict with success, status_code, dns_ms, tcp_connect_ms, tls_ms,
        ttfb_ms, total_ms, size_bytes, speed_bps, error_type, raw_error.
    """
    try:
        validate_http_url(url)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    return _run_curl(url, method=method, timeout_s=timeout_s)


if __name__ == "__main__":
    import json
    import sys
    if len(sys.argv) > 1:
        print(json.dumps(http_probe(sys.argv[1]), indent=2))
    else:
        print("Usage: python http_probe_tool.py <url>")
