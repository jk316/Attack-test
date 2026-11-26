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
from src.tools.rtt_window import build_rtt_observation
from src.tools.http_monitor import get_http_monitor
from src.tools.http_window import build_http_observation

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


def _get_dst_mac() -> str:
    """Read dst_mac from topology.yaml, falling back to hardcoded default."""
    try:
        import yaml
        from pathlib import Path as _Path
        topology_path = _Path(__file__).resolve().parent.parent.parent / "topology.yaml"
        with open(topology_path) as f:
            data = yaml.safe_load(f)
        return data.get("dst_mac", {}).get("portlist", "f0:c4:78:4c:a5:55")
    except Exception:
        return "f0:c4:78:4c:a5:55"


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

# ── Safety gate constants (005: G1 / G3 / D9) ─────────────────────────
DURATION_LIMIT_MS = 60000  # 宪法附加约束「Pktgen duration≤60000ms」；0 = 永久发包（合法）

# 合法源地址（D9）：experiment.json pktgen.src_ip 的默认值（005-T004），
# main.py 经 env PKTGEN_SRC_IP 注入；适配器调用时读取 env 优先、回退此默认，
# 覆盖 vendored YAML 的伪造默认 192.168.1.1/24。
_DEFAULT_CONFIGURED_SRC_IP = "10.99.80.10/24"

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

    In live mode, sleeps for the skill's duration after sending Lua so that
    ``rtt_during`` captures the full attack window (same synchronous behavior
    as Scapy tools).
    """
    execute_dry, execute_live = _import_pktgen()

    # Strip None values so Pktgen uses its own defaults
    clean_params = {k: v for k, v in params.items() if v is not None}

    # 008-T008：下发硬件前的 duration 显式钳制（宪法附加约束 duration≤60000ms）。
    # 工具层已按 005-G1 拒绝 >60000 请求；此处为引擎边界守卫，
    # 保证任何内部调用方下发的 duration 永不超过上限。
    duration = clean_params.get("duration")
    if (isinstance(duration, (int, float)) and not isinstance(duration, bool)
            and duration > DURATION_LIMIT_MS):
        logger.warning(
            "Clamping duration %s → %s ms before handing to Pktgen engine",
            duration, DURATION_LIMIT_MS,
        )
        clean_params["duration"] = DURATION_LIMIT_MS

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
            # Wait for traffic to complete so RTT sampling captures full attack
            _wait_for_attack(clean_params)
    except Exception as e:
        logger.error("Skill execution failed: skill=%s error=%s", skill_name, e)
        raw = {"success": False, "skill": skill_name,
               "error": str(e), "mode": "unknown"}

    return _normalize_result(raw, skill_name, clean_params)


def _wait_for_attack(params: dict[str, Any]) -> None:
    """Sleep while Pktgen traffic is in flight so RTT sampling is meaningful."""
    duration_ms = params.get("duration", 0)
    if isinstance(duration_ms, (int, float)) and duration_ms > 0:
        sleep_s = min(duration_ms / 1000.0, 60.0)  # cap at 60s for safety
        logger.info("Waiting %.1fs for Pktgen traffic to complete...", sleep_s)
        time.sleep(sleep_s)


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
        # 008 统一审批结构：mode 移入 params（message/params/scope 三键齐全）
        "params": {"skill": skill_name, "mode": "live", **params},
        "scope": "pktgen_traffic",
    })
    return bool(approval)


def _sample_rtt(result: dict[str, Any], t0: float) -> dict[str, Any]:
    """Attach RTT + HTTP observations (same pattern as traffic_send).

    Adds ``rtt_during`` + ``http_during`` plus attack/observation windows so the
    LLM can tell whether the observations actually covered the attack window.
    The mode reflects whether traffic was really sent (live) or not (dry_run).
    HTTP observation is unconditional (its target comes from http.url); it
    safely returns ``http_during=None`` when the monitor isn't running.
    """
    mode = "dry_run" if is_dry_run() else "live"
    try:
        monitor = get_ping_monitor()
    except Exception:
        monitor = None
    result.update(build_rtt_observation(monitor, t0, mode=mode))
    result.update(build_http_observation(get_http_monitor(), t0, mode=mode))
    return result


def _configured_src_ip() -> str:
    """D9：返回合法源地址（env PKTGEN_SRC_IP 优先，回退配置默认）。

    在编译前填入技能参数，覆盖 vendored YAML 的伪造默认源 192.168.1.1/24；
    操作员可按实验拓扑修改 experiment.json pktgen.src_ip（main.py 注入同名 env）。
    """
    return os.environ.get("PKTGEN_SRC_IP") or _DEFAULT_CONFIGURED_SRC_IP


def _default_rate() -> float:
    """008-T012/005-G4：rate 缺省时调用时读 env PKTGEN_RATE，回退签名默认 50。"""
    try:
        return float(os.environ.get("PKTGEN_RATE", "50"))
    except ValueError:
        return 50.0


def _default_duration_ms() -> int:
    """008-T012/005-G4：duration 缺省时调用时读 env PKTGEN_DURATION_MS，回退签名默认 5000。"""
    try:
        return int(os.environ.get("PKTGEN_DURATION_MS", "5000"))
    except ValueError:
        return 5000


def _src_ip_rejection(skill_name: str) -> dict[str, Any]:
    """G3：LLM 传入 src_ip 的拒绝结果（禁止源 IP 伪造）。"""
    return {
        "success": False,
        "skill": skill_name,
        "mode": "unknown",
        "error": "src_ip 不允许自定义（禁止源 IP 伪造；"
                 "合法源地址来自配置 PKTGEN_SRC_IP）",
    }


def _validate_traffic_params(skill_name: str, params: dict[str, Any]) -> dict[str, Any] | None:
    """G1 前置校验（执行/编译前）：duration 上限违规返回错误结果，合规返回 None。

    校验必须先于 allowlist / HITL / 编译执行（data-model 状态流转），
    违规即止——零编译零流量。
    """
    duration = params.get("duration")
    if duration is not None and duration > DURATION_LIMIT_MS:
        return {
            "success": False,
            "skill": skill_name,
            "mode": "unknown",
            "error": f"duration {duration} exceeds maximum {DURATION_LIMIT_MS} ms",
        }
    return None


def _run_traffic_tool(
    skill_name: str,
    params: dict[str, Any],
    dst_ip: str | None = None,
) -> dict[str, Any]:
    """Common execution path for traffic-generating Pktgen tools.

    1. Duration 上限校验（G1，失败即止）
    2. Allowlist check (if *dst_ip* provided)
    3. HITL gate
    4. Execute skill
    5. RTT sampling
    """
    error_result = _validate_traffic_params(skill_name, params)
    if error_result is not None:
        return error_result
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
    rate: float | None = None,
    duration: int | None = None,
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
    faster than Scapy.  Use this when you need higher throughput than
    ``traffic_send`` can provide to saturate the link.

    Rate is a PERCENTAGE (0–100) of the port's maximum rate, NOT packets per
    second.  Duration is in MILLISECONDS (5000 = 5 seconds).

    Args:
        dst_ip: Destination IP address (must be in allowlist).  Default
                ``10.10.10.2`` (Pktgen default).
        rate: Packet rate as percentage of line-rate (0–100, default 50).
        duration: Traffic duration in **milliseconds** (0 = forever,
                  default 5000 = 5 s).  Requests above 60000 ms are REJECTED
                  (hard limit; use 0 for forever and ``pktgen_stop_and_reset``
                  to terminate).
        dport: UDP destination port (default 5678).
        sport: UDP source port (default 1234).
        pktSize: Packet size in bytes (64–1518, default 256).
        src_ip: **Forbidden** — custom source IPs are rejected (no src-IP
                forgery).  The legal source comes from configuration
                (``PKTGEN_SRC_IP`` / experiment.json ``pktgen.src_ip``),
                overriding the vendored default.
        count: Number of packets (0 = forever, default 0).
        burst: Tx burst size (default 128).

    Returns:
        Dict with ``success``, ``skill``, ``params``, ``lua_code``,
        ``mode`` (dry_run/live), ``response`` (live only), and
        ``rtt_during`` (if ping monitor is active).
    """
    if src_ip:
        return _src_ip_rejection("udp_flood")
    rate = _default_rate() if rate is None else rate
    duration = _default_duration_ms() if duration is None else duration
    return _run_traffic_tool("udp_flood", {
        "dst_ip": dst_ip, "rate": rate, "duration": duration,
        "dport": dport, "sport": sport, "pktSize": pktSize,
        "src_ip": _configured_src_ip(), "count": count, "burst": burst,
    }, dst_ip=dst_ip)


# ── Tool: pktgen_tcp_flood ───────────────────────────────────────────

@tool
def pktgen_tcp_flood(
    dst_ip: str = "",
    rate: float | None = None,
    duration: int | None = None,
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
        duration: Traffic duration in **milliseconds** (default 5000;
                  >60000 rejected; 0 = forever).
        dport: TCP destination port (default 5678).
        sport: TCP source port (default 1234).
        tcp_flags: TCP flags string — ``syn``, ``ack``, ``rst``, ``fin``,
                   or comma-separated like ``syn,ack``.  Default ``ack``.
        pktSize: Packet size in bytes (64–1518, default 256).
        src_ip: **Forbidden** — custom source IPs are rejected (no src-IP
                forgery); the legal source comes from configuration
                (``PKTGEN_SRC_IP`` / experiment.json ``pktgen.src_ip``).
        count: Number of packets (0 = forever).
        burst: Tx burst size (default 128).

    Returns:
        Dict with ``success``, ``skill``, ``params``, ``lua_code``,
        ``mode``, ``response`` (live), ``rtt_during``.
    """
    if src_ip:
        return _src_ip_rejection("tcp_flood")
    rate = _default_rate() if rate is None else rate
    duration = _default_duration_ms() if duration is None else duration
    return _run_traffic_tool("tcp_flood", {
        "dst_ip": dst_ip, "rate": rate, "duration": duration,
        "dport": dport, "sport": sport, "tcp_flags": tcp_flags,
        "pktSize": pktSize, "src_ip": _configured_src_ip(),
        "count": count, "burst": burst,
    }, dst_ip=dst_ip)


# ── Tool: pktgen_icmp_flood ──────────────────────────────────────────

@tool
def pktgen_icmp_flood(
    dst_ip: str = "",
    rate: float | None = None,
    duration: int | None = None,
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
        duration: Traffic duration in **milliseconds** (default 5000;
                  >60000 rejected; 0 = forever).
        pktSize: Packet size in bytes (64–1518, default 256).
        ttl: IP Time-To-Live (default 64).
        src_ip: **Forbidden** — custom source IPs are rejected (no src-IP
                forgery); the legal source comes from configuration
                (``PKTGEN_SRC_IP`` / experiment.json ``pktgen.src_ip``).
        count: Number of packets (0 = forever).
        burst: Tx burst size (default 128).

    Returns:
        Dict with ``success``, ``skill``, ``params``, ``lua_code``,
        ``mode``, ``response`` (live), ``rtt_during``.
    """
    if src_ip:
        return _src_ip_rejection("icmp_flood")
    rate = _default_rate() if rate is None else rate
    duration = _default_duration_ms() if duration is None else duration
    return _run_traffic_tool("icmp_flood", {
        "dst_ip": dst_ip, "rate": rate, "duration": duration,
        "pktSize": pktSize, "ttl": ttl, "src_ip": _configured_src_ip(),
        "count": count, "burst": burst,
    }, dst_ip=dst_ip)


# ── Tool: pktgen_arp_flood ───────────────────────────────────────────

@tool
def pktgen_arp_flood(
    rate: float | None = None,
    duration: int | None = None,
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
    it is only used for RTT sampling via the program-owned PingMonitor
    (auto-started at experiment begin) against that target.

    Args:
        rate: Packet rate as percentage of line-rate (0–100, default 50).
        duration: Traffic duration in **milliseconds** (default 5000;
                  >60000 rejected; 0 = forever).
        arp_type: ARP packet type — ``request``, ``req``, ``gratuitous``,
                  ``grat``, or ``g``.  Default ``request``.
        dst_ip: Target IP for RTT sampling only (NOT sent to Pktgen).
                Must be in allowlist when provided (otherwise rejected).
                Leave empty to skip RTT sampling.
        count: Number of packets (0 = forever).
        burst: Tx burst size (default 128).

    Returns:
        Dict with ``success``, ``skill``, ``params``, ``lua_code``,
        ``mode``, ``response`` (live), and ``rtt_during`` if *dst_ip*
        is provided.
    """
    # G2（005-T008）：提供 dst_ip 时必须过 allowlist（白名单/广播/组播），
    # 失败即拒绝；不提供仍允许（ARP L2 语义），仅跳过 RTT 采样。
    if dst_ip:
        try:
            validate_target(dst_ip)
        except ValueError as e:
            return {"success": False, "mode": "unknown", "error": str(e)}
    rate = _default_rate() if rate is None else rate
    duration = _default_duration_ms() if duration is None else duration
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
    rate: float | None = None,
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
    rate = _default_rate() if rate is None else rate
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
        ``mode``, ``response`` (live), ``rtt_during``.  Fabricated / missing
        ``eth_dst_addr`` entries are auto-filled with the real ``dst_mac``
        from topology.yaml and reported in ``replaced_mac``
        (``[{"index": i, "from": old, "to": new}]``; the key appears only
        when a replacement actually happened).
    """
    # Parse JSON string to Python list for the compiler
    try:
        seq_list = json.loads(sequences) if isinstance(sequences, str) else sequences
    except json.JSONDecodeError:
        return {"success": False, "error": f"Invalid JSON for sequences: {sequences[:200]}"}

    # Auto-fill eth_dst_addr from topology.yaml when missing or obviously
    # fabricated — the LLM doesn't know the real dst_mac and tends to
    # invent numbers like 00:00:00:00:00:01.
    dst_mac_default = _get_dst_mac()
    replaced_mac: list[dict[str, Any]] = []
    for i, entry in enumerate(seq_list):
        eth = (entry.get("eth_dst_addr") or "").strip()
        # Missing, empty, or clearly fabricated (all-zeros prefix pattern
        # like 00:00:00:00:00:01) → replace with real dst_mac.
        digits = eth.replace(":", "").replace("-", "")
        if not eth or set(digits) <= {"0", "1"}:
            logger.info(
                "packet_sequence: replacing fabricated eth_dst_addr[%d] %r → %s",
                i, eth, dst_mac_default,
            )
            entry["eth_dst_addr"] = dst_mac_default
            # G5（005-T016）：替换明细进结果，与 logger 记录保持一致
            replaced_mac.append({"index": i, "from": eth, "to": dst_mac_default})

    result = _run_traffic_tool("packet_sequence_generation", {
        "sequences": seq_list, "rate": rate,
        "count": count, "burst": burst, "dst_ip": dst_ip,
    }, dst_ip=dst_ip)
    if replaced_mac:
        # 契约 pktgen-adapter-results.md §2：仅实际发生替换时出现该字段
        result["replaced_mac"] = replaced_mac
    return result


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

    In dry-run mode (default) this only compiles/validates the script and
    does NOT connect to the hardware (决策 005-2: the default mode never
    touches the network).

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

    In dry-run mode (default) this only compiles/validates the script and
    does NOT connect to the hardware — it does not actually stop a live
    Pktgen (决策 005-2).  Real stop/reset requires live mode.

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
