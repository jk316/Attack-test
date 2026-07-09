"""Pktgen Agent tool adapters for Attack-Test — LangChain @tool wrappers.

Wraps the 9 Pktgen-DPDK skills (from the vendored ``pktgen_agent`` package) as
Attack-Test-compatible ``@tool`` functions.  Each adapter:

1. Enforces Attack-Test's allowlist via ``validate_target()``
2. Adds a HITL gate via ``interrupt()`` (traffic tools in live mode only)
3. Calls ``execute_skill_dry_run()`` or ``execute_skill_live()`` from Pktgen
4. Attaches RTT samples from the background PingMonitor when available

Default mode is **dry-run**: the Lua script is compiled and saved but NOT sent
to Pktgen.  Set ``PKTGEN_DRY_RUN=false`` or pass ``--pktgen-live`` for live
execution.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

from langchain.tools import tool
from langgraph.types import interrupt

from src.tools.ping_monitor import get_ping_monitor
from src.tools.ping_rtt_tool import validate_target

logger = logging.getLogger(__name__)

# ── Ensure pktgen_agent is importable ────────────────────────────────
# The vendored pktgen_agent/ lives at the project root, not under src/.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ── Configuration ────────────────────────────────────────────────────

def _get_default_host() -> str:
    """Read Pktgen host from topology.yaml, falling back to env var."""
    try:
        from pktgen_agent.topology import load_topology_config
        host, _ = load_topology_config()
        return host
    except Exception:
        return "10.99.80.222"


def _get_default_port() -> int:
    """Read Pktgen port from topology.yaml, falling back to env var."""
    try:
        from pktgen_agent.topology import load_topology_config
        _, port = load_topology_config()
        return port
    except Exception:
        return 22022


# Environment overrides take priority over topology.yaml.
# These are FUNCTIONS (not constants) so that main() can set env vars
# AFTER module import — the values are re-evaluated at each call.


def get_pktgen_host() -> str:
    """Return Pktgen host, re-reading env var on each call."""
    return os.environ.get("PKTGEN_HOST") or _get_default_host()


def get_pktgen_port() -> int:
    """Return Pktgen port, re-reading env var on each call."""
    return int(os.environ.get("PKTGEN_PORT", "0")) or _get_default_port()


def is_dry_run() -> bool:
    """Return True if Pktgen is in dry-run mode, re-reading env var on each call."""
    return os.environ.get("PKTGEN_DRY_RUN", "true").lower() != "false"

# ── Skills that require allowlist validation (have dst_ip param) ─────
_SKILLS_WITH_DST_IP = {
    "udp_flood", "tcp_flood", "icmp_flood",
    "range_based_scan", "packet_sequence_generation",
}

# ── Skills that require HITL gate (traffic-generating skills) ────────
_SKILLS_WITH_HITL = {
    "udp_flood", "tcp_flood", "icmp_flood", "arp_flood",
    "range_based_scan", "packet_sequence_generation", "pcap_replay",
}

# ── Helpers ──────────────────────────────────────────────────────────

_pktgen_exec_cache: tuple | None = None


def _import_pktgen():
    """Lazy-import Pktgen execution functions, cached after first call.

    Raises ImportError with actionable instructions if the vendored
    ``pktgen_agent`` package is not on ``sys.path``.
    """
    global _pktgen_exec_cache
    if _pktgen_exec_cache is not None:
        return _pktgen_exec_cache

    try:
        from pktgen_agent.tools.execute import (  # type: ignore[import-not-found]
            execute_skill_dry_run,
            execute_skill_live,
        )
        _pktgen_exec_cache = (execute_skill_dry_run, execute_skill_live)
        return _pktgen_exec_cache
    except ImportError:
        raise ImportError(
            "Pktgen Agent not found on sys.path.  "
            "The vendored pktgen_agent/ package should be at the project root:\n"
            f"  {_PROJECT_ROOT}\n"
            "Ensure the project root is on sys.path before importing this module."
        )


def _normalize_result(
    raw: dict[str, Any], skill_name: str, params: dict[str, Any]
) -> dict[str, Any]:
    """Enrich Pktgen engine result with agent-friendly metadata.

    Adds ``summary`` (one-line result) and ``artifacts`` (script path), and
    classifies errors so the LLM can decide recovery strategy.  Does NOT add
    hardcoded ``next_actions`` — the ReAct agent reasons about next steps on
    its own.
    """
    raw["summary"] = _build_summary(raw, skill_name)

    # Truncate lua_code to save context budget; store path as artifact
    lua_code = raw.pop("lua_code", None)
    if lua_code:
        ts = time.strftime("%Y%m%d_%H%M%S")
        raw["artifacts"] = {
            "lua_script": f"lua_scripts/{ts}_{skill_name}.lua",
            "lua_preview": lua_code[:200] + ("..." if len(lua_code) > 200 else ""),
        }

    return raw


def _build_summary(raw: dict[str, Any], skill_name: str) -> str:
    """Build a one-line human + LLM readable summary of the result."""
    success = raw.get("success", False)
    mode = raw.get("mode", "unknown")
    if success:
        return f"Pktgen '{skill_name}' succeeded ({mode} mode)."
    error = raw.get("error", "unknown error")
    if "Connection failed" in error or "Connection" in error:
        return f"Pktgen '{skill_name}' failed: Pktgen unreachable — fall back to Scapy tools."
    if "CompileError" in str(error) or "required" in str(error).lower():
        return f"Pktgen '{skill_name}' failed: parameter error — {error}"
    return f"Pktgen '{skill_name}' failed: {error}"


def _execute_skill(skill_name: str, params: dict[str, Any]) -> dict[str, Any]:
    """Execute a Pktgen skill (dry-run or live), return normalized dict.

    Both ``execute_skill_dry_run`` and ``execute_skill_live`` return
    ``dict[str, Any]`` directly (never a JSON string), so no parsing needed.
    """
    execute_dry, execute_live = _import_pktgen()

    # Strip None values so Pktgen uses its own defaults
    clean_params = {k: v for k, v in params.items() if v is not None}

    try:
        if is_dry_run():
            logger.info("Dry-run: skill=%s params=%s", skill_name, clean_params)
            raw = execute_dry(skill_name, clean_params)
        else:
            host = get_pktgen_host()
            port = get_pktgen_port()
            logger.info("Live: skill=%s params=%s host=%s:%s",
                         skill_name, clean_params, host, port)
            raw = execute_live(skill_name, clean_params, host=host, port=port)
    except Exception as e:
        logger.error("Skill execution failed: skill=%s error=%s", skill_name, e)
        raw = {"success": False, "skill": skill_name,
               "error": str(e), "mode": "unknown"}

    return _normalize_result(raw, skill_name, clean_params)


def _apply_allowlist(dst_ip: str | None, skill_name: str) -> None:
    """Validate *dst_ip* against Attack-Test's allowlist.

    Raises ValueError if *dst_ip* is empty or not in the allowlist.
    """
    if not dst_ip:
        raise ValueError(
            f"Pktgen skill '{skill_name}' requires dst_ip (must be in allowlist). "
            f"The LLM must provide a valid target IP."
        )
    validate_target(dst_ip)


def _hitl_gate(skill_name: str, params: dict[str, Any]) -> bool:
    """Prompt for human approval before executing a traffic skill.

    Skipped in dry-run mode (no traffic is actually sent).  This function
    is only reached when ``is_dry_run()`` returns False.
    """
    if is_dry_run():
        return True
    approval = interrupt({
        "message": f"[HITL] Approve Pktgen '{skill_name}' execution?",
        "mode": "live",
        "params": params,
    })
    return bool(approval)


def _sample_rtt(result: dict[str, Any], t0: float) -> dict[str, Any]:
    """Attach RTT samples from the PingMonitor (same pattern as traffic_send)."""
    try:
        monitor = get_ping_monitor()
        if monitor.is_running():
            rtt_samples = monitor.get_samples_since(t0)
            if rtt_samples:
                rtt_values = [s["rtt_ms"] for s in rtt_samples]
                result["rtt_during"] = {
                    "samples": rtt_samples,
                    "avg_rtt_ms": round(sum(rtt_values) / len(rtt_values), 3),
                    "min_rtt_ms": round(min(rtt_values), 3),
                    "max_rtt_ms": round(max(rtt_values), 3),
                }
            else:
                result["rtt_during"] = None
        else:
            result["rtt_during"] = None
    except Exception:
        result["rtt_during"] = None
    return result


def _run_traffic_tool(
    skill_name: str,
    params: dict[str, Any],
    dst_ip: str | None = None,
) -> dict[str, Any]:
    """Common execution path for traffic-generating Pktgen tools.

    1. Allowlist check (if *dst_ip* provided)
    2. HITL gate
    3. Execute skill
    4. RTT sampling
    """
    if skill_name in _SKILLS_WITH_DST_IP:
        _apply_allowlist(dst_ip, skill_name)
    if skill_name in _SKILLS_WITH_HITL:
        if not _hitl_gate(skill_name, params):
            return {"success": False, "error": "HITL rejected by operator"}
    t0 = time.time()
    result = _execute_skill(skill_name, params)
    if dst_ip:
        result = _sample_rtt(result, t0)
    return result


# ── Tool: pktgen_udp_flood ───────────────────────────────────────────

@tool
def pktgen_udp_flood(
    dst_ip: str = "",
    rate: float = 50.0,
    duration: int = 5000,
    dport: int | None = None,
    sport: int | None = None,
    pktSize: int | None = None,
    src_ip: str | None = None,
    count: int | None = None,
    burst: int | None = None,
) -> dict[str, Any]:
    """Send a UDP packet flood via Pktgen-DPDK at hardware line-rate.  REQUIRES
    HUMAN APPROVAL in live mode.

    Pktgen generates UDP traffic at the DPDK level — orders of magnitude
    faster than Scapy.  Use this when ``traffic_send`` hits its 200 pps
    ceiling and you need higher throughput to saturate the link.

    Rate is a PERCENTAGE (0–100) of the port's maximum rate, NOT packets per
    second.  Duration is in MILLISECONDS (5000 = 5 seconds).

    Args:
        dst_ip: Destination IP address (must be in allowlist).  Default
                ``10.10.10.2`` (Pktgen default).
        rate: Packet rate as percentage of line-rate (0–100, default 50).
        duration: Traffic duration in **milliseconds** (0 = forever,
                  default 5000 = 5 s).
        dport: UDP destination port (default 5678).
        sport: UDP source port (default 1234).
        pktSize: Packet size in bytes (64–1518, default 256).
        src_ip: Source IP in CIDR notation (default ``192.168.1.1/24``).
        count: Number of packets (0 = forever, default 0).
        burst: Tx burst size (default 128).

    Returns:
        Dict with ``success``, ``skill``, ``params``, ``lua_code``,
        ``mode`` (dry_run/live), ``response`` (live only), and
        ``rtt_during`` (if ping monitor is active).
    """
    return _run_traffic_tool("udp_flood", {
        "dst_ip": dst_ip, "rate": rate, "duration": duration,
        "dport": dport, "sport": sport, "pktSize": pktSize,
        "src_ip": src_ip, "count": count, "burst": burst,
    }, dst_ip=dst_ip)


# ── Tool: pktgen_tcp_flood ───────────────────────────────────────────

@tool
def pktgen_tcp_flood(
    dst_ip: str = "",
    rate: float = 50.0,
    duration: int = 5000,
    dport: int | None = None,
    sport: int | None = None,
    tcp_flags: str = "ack",
    pktSize: int | None = None,
    src_ip: str | None = None,
    count: int | None = None,
    burst: int | None = None,
) -> dict[str, Any]:
    """Send a TCP packet flood via Pktgen-DPDK at hardware line-rate.  REQUIRES
    HUMAN APPROVAL in live mode.

    Supports configurable TCP flags — use ``syn`` for SYN flood, ``ack`` for
    ACK flood, or combined flags like ``fin,ack``.

    Args:
        dst_ip: Destination IP address (must be in allowlist).
        rate: Packet rate as percentage of line-rate (0–100, default 50).
        duration: Traffic duration in **milliseconds** (default 5000).
        dport: TCP destination port (default 5678).
        sport: TCP source port (default 1234).
        tcp_flags: TCP flags string — ``syn``, ``ack``, ``rst``, ``fin``,
                   or comma-separated like ``syn,ack``.  Default ``ack``.
        pktSize: Packet size in bytes (64–1518, default 256).
        src_ip: Source IP in CIDR notation.
        count: Number of packets (0 = forever).
        burst: Tx burst size (default 128).

    Returns:
        Dict with ``success``, ``skill``, ``params``, ``lua_code``,
        ``mode``, ``response`` (live), ``rtt_during``.
    """
    return _run_traffic_tool("tcp_flood", {
        "dst_ip": dst_ip, "rate": rate, "duration": duration,
        "dport": dport, "sport": sport, "tcp_flags": tcp_flags,
        "pktSize": pktSize, "src_ip": src_ip,
        "count": count, "burst": burst,
    }, dst_ip=dst_ip)


# ── Tool: pktgen_icmp_flood ──────────────────────────────────────────

@tool
def pktgen_icmp_flood(
    dst_ip: str = "",
    rate: float = 50.0,
    duration: int = 5000,
    pktSize: int | None = None,
    ttl: int | None = None,
    src_ip: str | None = None,
    count: int | None = None,
    burst: int | None = None,
) -> dict[str, Any]:
    """Send an ICMP Echo Request flood via Pktgen-DPDK at hardware line-rate.
    REQUIRES HUMAN APPROVAL in live mode.

    ICMP has no port numbers — uses TTL instead.  Flooding ICMP while the
    ping monitor is active can directly reveal how the target's ICMP reply
    path degrades under load.

    Args:
        dst_ip: Destination IP address (must be in allowlist).
        rate: Packet rate as percentage of line-rate (0–100, default 50).
        duration: Traffic duration in **milliseconds** (default 5000).
        pktSize: Packet size in bytes (64–1518, default 256).
        ttl: IP Time-To-Live (default 64).
        src_ip: Source IP in CIDR notation.
        count: Number of packets (0 = forever).
        burst: Tx burst size (default 128).

    Returns:
        Dict with ``success``, ``skill``, ``params``, ``lua_code``,
        ``mode``, ``response`` (live), ``rtt_during``.
    """
    return _run_traffic_tool("icmp_flood", {
        "dst_ip": dst_ip, "rate": rate, "duration": duration,
        "pktSize": pktSize, "ttl": ttl, "src_ip": src_ip,
        "count": count, "burst": burst,
    }, dst_ip=dst_ip)


# ── Tool: pktgen_arp_flood ───────────────────────────────────────────

@tool
def pktgen_arp_flood(
    rate: float = 50.0,
    duration: int = 5000,
    arp_type: str = "request",
    dst_ip: str = "",
    count: int | None = None,
    burst: int | None = None,
) -> dict[str, Any]:
    """Send an ARP packet flood via Pktgen-DPDK at hardware line-rate.  REQUIRES
    HUMAN APPROVAL in live mode.

    ARP operates at Layer 2 — there are no IP addresses or port numbers.
    This can saturate the local broadcast domain, causing different RTT
    degradation patterns than L3/L4 floods.

    The optional *dst_ip* is NOT sent to Pktgen (ARP has no IP fields);
    it is only used for RTT sampling via the PingMonitor against that target.
    Provide the same IP used for ``start_ping_monitor`` to correlate RTT
    impact.

    Args:
        rate: Packet rate as percentage of line-rate (0–100, default 50).
        duration: Traffic duration in **milliseconds** (default 5000).
        arp_type: ARP packet type — ``request``, ``req``, ``gratuitous``,
                  ``grat``, or ``g``.  Default ``request``.
        dst_ip: Target IP for RTT sampling only (NOT sent to Pktgen).
                Must be in allowlist.  Leave empty to skip RTT sampling.
        count: Number of packets (0 = forever).
        burst: Tx burst size (default 128).

    Returns:
        Dict with ``success``, ``skill``, ``params``, ``lua_code``,
        ``mode``, ``response`` (live), and ``rtt_during`` if *dst_ip*
        is provided.
    """
    t0 = time.time()
    result = _run_traffic_tool("arp_flood", {
        "rate": rate, "duration": duration, "arp_type": arp_type,
        "count": count, "burst": burst,
    })
    if dst_ip:
        result = _sample_rtt(result, t0)
    return result


# ── Tool: pktgen_range_scan ──────────────────────────────────────────

@tool
def pktgen_range_scan(
    dst_ip: str = "",
    scan_field: str = "dst_port",
    start: str = "1",
    min_val: str = "1",
    max_val: str = "65535",
    inc: str = "1",
    rate: float = 50.0,
    pktSize: int | None = None,
    count: int | None = None,
) -> dict[str, Any]:
    """Run an automated parameter-range scan via Pktgen-DPDK.  REQUIRES HUMAN
    APPROVAL in live mode.

    Pktgen varies one field per packet across [min, max] by increment, wrapping
    back to min after max.  This is Pktgen's HARDWARE-level iteration — far
    faster than the agent's software ReAct loop.  Use it for brute-force
    parameter sweeps (e.g. scan all dst ports, sweep packet sizes, vary IPs).

    Args:
        dst_ip: Destination IP address (must be in allowlist).  If empty, uses
                Pktgen's default.
        scan_field: Which field to vary — ``dst_ip``, ``src_ip``, ``dst_port``,
                    ``src_port``, ``dst_mac``, ``src_mac``, ``vlan_id``,
                    or ``pkt_size``.  Default ``dst_port``.
        start: Starting value for the scan (string form — IP, MAC, or integer).
               Default ``"1"``.
        min_val: Minimum / wrap-lower-bound value.  Default ``"1"``.
        max_val: Maximum / wrap-upper-bound value.  Default ``"65535"``.
        inc: Increment per packet (0 = no variation).  Default ``"1"``.
        rate: Packet rate as percentage (0–100, default 50).
        pktSize: Packet size in bytes (64–1518, default 128).
        count: Number of packets (0 = forever).

    Returns:
        Dict with ``success``, ``skill``, ``params``, ``lua_code``,
        ``mode``, ``response`` (live), ``rtt_during``.
    """
    return _run_traffic_tool("range_based_scan", {
        "scan_field": scan_field, "start": start,
        "min": min_val, "max": max_val, "inc": inc,
        "rate": rate, "pktSize": pktSize, "count": count,
        "dst_ip": dst_ip,
    }, dst_ip=dst_ip)


# ── Tool: pktgen_packet_sequence ─────────────────────────────────────

@tool
def pktgen_packet_sequence(
    dst_ip: str = "",
    sequences: str = "[]",
    rate: float = 100.0,
    count: int | None = None,
    burst: int | None = None,
) -> dict[str, Any]:
    """Send a sequence of distinct packet templates via Pktgen-DPDK seqTable.
    REQUIRES HUMAN APPROVAL in live mode.

    Each entry in the sequence defines a complete packet (MACs, IPs, ports,
    protocol, size, VLAN).  Up to 16 entries per port.  Pktgen cycles through
    them in order.  This is like ``mixed_traffic_send`` but at DPDK line-rate
    with hardware-level sequencing.

    Args:
        dst_ip: Destination IP address (must be in allowlist).  Individual
                sequence entries can override this.
        sequences: JSON array of sequence entry objects.  Each entry requires
                   ``eth_dst_addr``, ``eth_src_addr``, ``ip_dst_addr``,
                   ``ip_src_addr``, ``sport``, ``dport``, ``ethType``,
                   ``ipProto``, ``vlanid``, ``pktSize``.
                   Optional: ``teid``, ``cos``, ``tos``, ``tcp_flags``.
                   Example: ``[{"eth_dst_addr": "00:11:44:55:66:77", ...}]``
        rate: Packet rate as percentage (0–100, default 100).
        count: Number of packets (0 = forever).
        burst: Tx burst size (default 128).

    Returns:
        Dict with ``success``, ``skill``, ``params``, ``lua_code``,
        ``mode``, ``response`` (live), ``rtt_during``.
    """
    # Parse JSON string to Python list for the compiler
    try:
        seq_list = json.loads(sequences) if isinstance(sequences, str) else sequences
    except json.JSONDecodeError:
        return {"success": False, "error": f"Invalid JSON for sequences: {sequences[:200]}"}

    return _run_traffic_tool("packet_sequence_generation", {
        "sequences": seq_list, "rate": rate,
        "count": count, "burst": burst, "dst_ip": dst_ip,
    }, dst_ip=dst_ip)


# ── Tool: pktgen_pcap_replay ─────────────────────────────────────────

@tool
def pktgen_pcap_replay(
    pcap_file: str,
    rate: float = 100.0,
    count: int | None = None,
) -> dict[str, Any]:
    """Replay packets from a PCAP file via Pktgen-DPDK.  REQUIRES HUMAN APPROVAL
    in live mode.

    The PCAP file MUST be accessible from the Pktgen host (not the Attack-Test
    host) — Pktgen loads the file directly.  Use this to replay captured
    traffic patterns at hardware line-rate.

    Args:
        pcap_file: Path to the PCAP file **on the Pktgen host**.
        rate: Packet rate as percentage (0–100, default 100).
        count: Number of packets to send (0 = entire file, loop forever).

    Returns:
        Dict with ``success``, ``skill``, ``params``, ``lua_code``,
        ``mode``, ``response`` (live).
    """
    return _run_traffic_tool("pcap_replay", {
        "pcap_file": pcap_file, "rate": rate, "count": count,
    })


# ── Tool: pktgen_stats_monitor ───────────────────────────────────────

@tool
def pktgen_stats_monitor(
    interval_ms: int = 1000,
    iterations: int = 10,
    mode: str = "all",
) -> dict[str, Any]:
    """Poll Pktgen port statistics at a configurable interval.  Does NOT generate
    traffic and does NOT require human approval.

    Reports link state, sending status, packet counters, and rate stats from
    the Pktgen ports.  Use this to monitor the effect of ongoing traffic (e.g.
    observe port-level packet loss or rate drops while a flood is running).

    Args:
        interval_ms: Polling interval in milliseconds (default 1000).
        iterations: Number of polling iterations (0 = run until interrupted,
                    default 10).
        mode: What stats to collect — ``all``, ``link``, ``sending``,
              ``rates``, ``packets``, or ``port``.  Default ``all``.

    Returns:
        Dict with ``success``, ``skill``, ``params``, ``lua_code``,
        ``mode``, ``response`` (live).
    """
    return _execute_skill("stats_monitoring", {
        "interval_ms": interval_ms, "iterations": iterations, "mode": mode,
    })


# ── Tool: pktgen_stop_and_reset ──────────────────────────────────────

@tool
def pktgen_stop_and_reset(
    save_config: bool = False,
    clear_stats: bool = True,
    reset_ports: bool = True,
) -> dict[str, Any]:
    """Safely stop all Pktgen traffic and reset ports to defaults.  Does NOT
    require human approval (stopping should never be blocked).

    Idempotent — safe to call at any time, even if no traffic is running.
    Call this before switching between Pktgen flood types or at the end of
    the experiment as cleanup.

    Args:
        save_config: Save current config before reset (default False).
        clear_stats: Clear port statistics after stopping (default True).
        reset_ports: Reset port configuration to defaults (default True).

    Returns:
        Dict with ``success``, ``skill``, ``params``, ``lua_code``,
        ``mode``, ``response`` (live).
    """
    return _execute_skill("safe_stop_and_reset", {
        "save_config": save_config,
        "clear_stats": clear_stats,
        "reset_ports": reset_ports,
    })


# ── Tool list ────────────────────────────────────────────────────────

PKTGEN_TOOLS = [
    pktgen_udp_flood,
    pktgen_tcp_flood,
    pktgen_icmp_flood,
    pktgen_arp_flood,
    pktgen_range_scan,
    pktgen_packet_sequence,
    pktgen_pcap_replay,
    pktgen_stats_monitor,
    pktgen_stop_and_reset,
]
