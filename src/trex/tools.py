"""TRex client tools: generate + execute Python scripts (narrowed write+bash).

TRex uses a client-server architecture: the agent (client) writes a Python
script that drives the TRex server via its STL/ASTF Python API, then runs it.

These two tools are a narrowed form of `write` + `bash`: the LLM can generate
arbitrary Python, but never gets a raw shell or writes outside the sandbox
directory.

SAFETY NOTE (important): only the *file write* is confined to trex_scripts/.
The subprocess that runs the script has the agent's full user permissions — it
is NOT executed inside an OS-level sandbox. The real safety gates are:
  * dry-run default (no execution unless --trex-live)
  * HITL approval showing the script before live execution
  * a best-effort static scan for non-allowlisted IP literals (NOT a hard
    boundary — obfuscated IPs / domain names bypass it)
  * a subprocess timeout
"""
import logging
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from langchain.tools import tool
from langgraph.types import interrupt

from src.tools.ping_monitor import get_ping_monitor
from src.tools.ping_rtt_tool import ALLOWLIST, is_valid_ip, validate_target
from src.tools.rtt_window import build_rtt_observation
from src.trex.config import (
    get_trex_host,
    get_trex_scripts_dir,
    get_trex_timeout_s,
    is_trex_dry_run,
)

logger = logging.getLogger("agent")

MAX_SCRIPT_CHARS = 100_000
MAX_SCRIPT_LINES = 2_000
MAX_OUTPUT_CHARS = 4_000
CODE_PREVIEW_CHARS = 500

_IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_BARE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.py$")
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def _resolve_script_path(filename: str) -> Path:
    """Resolve a bare `*.py` name into the sandbox dir, rejecting anything else."""
    if not filename or not isinstance(filename, str):
        raise ValueError("filename must be a non-empty string")
    if not _BARE_NAME_RE.match(filename):
        raise ValueError(
            f"Invalid filename (must be a bare *.py name, no directories): {filename!r}"
        )
    if filename[:-3].upper() in _WINDOWS_RESERVED:
        raise ValueError(f"Reserved filename not allowed: {filename!r}")
    return get_trex_scripts_dir() / filename


def _compile_check(source: str, name: str) -> tuple[bool, str | None]:
    """Parse-only syntax check (no execution) using the built-in compile()."""
    try:
        compile(source, name, "exec")
        return True, None
    except SyntaxError as e:
        return False, f"{e.msg} (line {e.lineno})"


def _extract_ipv4(code: str) -> list[str]:
    """Extract all dotted-quad IPv4 literals from the code."""
    return [m for m in _IPV4_RE.findall(code) if is_valid_ip(m)]


def _static_ip_guard(code: str) -> list[str]:
    """Best-effort: return non-allowlisted IP literals found in the code.

    This is NOT a hard security boundary — an obfuscated IP (string concat,
    inet_ntoa, hex/int, domain name) bypasses it. Excludes the TRex server
    host and loopback, which are legitimate.
    """
    server_host = get_trex_host()
    suspicious: list[str] = []
    for ip in _extract_ipv4(code):
        if ip in ALLOWLIST or ip == server_host or ip.startswith("127."):
            continue
        suspicious.append(ip)
    return list(dict.fromkeys(suspicious))  # dedupe, preserving order


def _truncate(text: str | None) -> str:
    """Truncate captured output to protect the context budget."""
    text = text or ""
    if len(text) > MAX_OUTPUT_CHARS:
        return text[:MAX_OUTPUT_CHARS] + f"… (+{len(text) - MAX_OUTPUT_CHARS} chars)"
    return text


@tool
def write_python_file(filename: str, code: str) -> dict[str, Any]:
    """Write a Python script into the TRex scripts directory and syntax-check it.

    Use this to produce the Python client script that drives the TRex server
    (STL/ASTF traffic generation). The file is written even if it has a syntax
    error, so a human can inspect and fix it. Syntax checking is parse-only
    (no execution). NOTE: the file is confined to trex_scripts/, but nothing
    here executes it.

    Args:
        filename: Bare script name ending in .py (no directories allowed).
        code: The full Python source code of the script.

    Returns:
        Dict with success, path, syntax_ok, syntax_error.
    """
    try:
        path = _resolve_script_path(filename)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    if len(code) > MAX_SCRIPT_CHARS:
        return {"success": False, "error": f"code exceeds {MAX_SCRIPT_CHARS} chars"}
    if len(code.splitlines()) > MAX_SCRIPT_LINES:
        return {"success": False, "error": f"code exceeds {MAX_SCRIPT_LINES} lines"}

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(code, encoding="utf-8")
    except (OSError, ValueError) as e:
        return {"success": False, "error": f"failed to write file: {e}"}

    syntax_ok, syntax_error = _compile_check(code, path.name)
    logger.info("TRex write_python_file: %s (syntax_ok=%s)", path.name, syntax_ok)
    return {
        "success": True,
        "path": str(path),
        "filename": path.name,
        "syntax_ok": syntax_ok,
        "syntax_error": syntax_error,
    }


def _read_and_scan(path: Path) -> dict[str, Any]:
    """Read the script and run syntax + static-IP checks.

    Returns either {"error": ...} on read failure, or a dict with the fields
    `code`, `syntax_ok`, `syntax_error`, `detected_ips`, `suspicious`.
    """
    try:
        code = path.read_text(encoding="utf-8")
    except (OSError, ValueError) as e:
        return {"error": f"failed to read script: {e}"}

    syntax_ok, syntax_error = _compile_check(code, str(path))
    return {
        "code": code,
        "syntax_ok": syntax_ok,
        "syntax_error": syntax_error,
        "detected_ips": _extract_ipv4(code),
        "suspicious": _static_ip_guard(code),
    }


def _execute_live(
    path: Path, code: str, target_ip: str | None, detected_ips: list[str],
) -> dict[str, Any]:
    """Run the script in live mode, after HITL approval."""
    approval = interrupt({
        "message": "[HITL] Approve executing a generated Python script?",
        "params": {
            "filename": path.name,
            "path": str(path),
            "target_ip": target_ip,
            "detected_ips": detected_ips,
            "code_preview": code[:CODE_PREVIEW_CHARS],
            "warning": "此脚本将以本机当前用户完整权限执行任意 Python（无执行沙箱），请确认脚本内容。",
        },
    })
    if not approval:
        return {"success": False, "mode": "live", "error": "HITL rejected by operator"}

    t0 = time.time()
    try:
        proc = subprocess.run(
            [sys.executable, str(path)],
            capture_output=True,
            text=True,
            timeout=get_trex_timeout_s(),
        )
    except subprocess.TimeoutExpired:
        logger.warning("TRex script %s timed out after %ss", path.name, get_trex_timeout_s())
        return {
            "success": False,
            "mode": "live",
            "error": f"script timed out after {get_trex_timeout_s()}s",
            "elapsed_s": round(time.time() - t0, 3),
            "detected_ips": detected_ips,
        }
    except OSError as e:
        logger.warning("TRex script %s failed to launch: %s", path.name, e)
        return {
            "success": False,
            "mode": "live",
            "error": f"failed to run script: {e}",
            "elapsed_s": round(time.time() - t0, 3),
        }

    result: dict[str, Any] = {
        "success": proc.returncode == 0,
        "mode": "live",
        "returncode": proc.returncode,
        "stdout": _truncate(proc.stdout),
        "stderr": _truncate(proc.stderr),
        "elapsed_s": round(time.time() - t0, 3),
        "detected_ips": detected_ips,
    }
    if result["success"]:
        logger.info("TRex script %s succeeded (%.3fs)", path.name, result["elapsed_s"])
    else:
        result["error"] = f"script exited with code {proc.returncode}"
        logger.warning(
            "TRex script %s failed (returncode=%s): %s",
            path.name, proc.returncode, result["stderr"][:200],
        )

    if target_ip:
        try:
            monitor = get_ping_monitor()
        except Exception:
            monitor = None
        result.update(build_rtt_observation(monitor, t0, mode="live"))

    return result


@tool
def run_python_file(filename: str, target_ip: str | None = None) -> dict[str, Any]:
    """Run a Python script from the TRex scripts directory.

    REQUIRES HUMAN APPROVAL in live mode. In dry-run mode the script is NOT
    executed (it only reports whether the file exists and parses cleanly).

    NOTE: in live mode this executes arbitrary Python with the agent's full
    user permissions — the operator approves the exact script (see the HITL
    prompt) before it runs.

    Args:
        filename: Script name in trex_scripts/ (must have been written by
                  write_python_file first).
        target_ip: Optional target IP the script attacks (must be in allowlist).

    Returns:
        Dict with success, returncode, stdout, stderr, elapsed_s, mode.
    """
    try:
        path = _resolve_script_path(filename)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    if not path.exists():
        return {"success": False, "error": f"script not found: {path} (write it first)"}

    if target_ip:
        try:
            validate_target(target_ip)
        except ValueError as e:
            return {"success": False, "error": str(e)}

    scan = _read_and_scan(path)
    if "error" in scan:
        return scan

    if is_trex_dry_run():
        return {
            "success": scan["syntax_ok"],
            "mode": "dry_run",
            "path": str(path),
            "syntax_ok": scan["syntax_ok"],
            "syntax_error": scan["syntax_error"],
            "detected_ips": scan["detected_ips"],
            "non_allowlisted_ips": scan["suspicious"],
            "message": "dry-run mode: script not executed.",
        }

    if not scan["syntax_ok"]:
        return {
            "success": False,
            "mode": "live",
            "error": f"script has a syntax error: {scan['syntax_error']}",
        }

    if scan["suspicious"]:
        return {
            "success": False,
            "mode": "live",
            "error": (
                f"script contains non-allowlisted IP(s) {scan['suspicious']}; "
                "add them to the allowlist or fix the code."
            ),
            "detected_ips": scan["detected_ips"],
            "non_allowlisted_ips": scan["suspicious"],
        }

    return _execute_live(path, scan["code"], target_ip, scan["detected_ips"])


TREX_TOOLS = [write_python_file, run_python_file]
