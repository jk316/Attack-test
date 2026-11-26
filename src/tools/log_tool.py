"""Log Tool — writes experiment results to a JSONL file in a canonical schema.

Canonical line schema (fixed top-level key order):

    {
      "run_id": "20261120T073000-a1b2c3",   # injected: env DSH_RUN_ID, else "unknown"
      "iteration": 3,
      "tool": "pktgen_udp_flood",            # injected when the LLM omits it
      "params": {
        "target_ip": "10.99.80.160",
        "dst_port": 80,
        "duration_ms": 5000,
        "pkt_size": 64,
        "pps": 100,
        "rate_pct": 50.0,                    # Pktgen line-rate percentage
        "protocol": "udp",
        "extras": {"tcp_flags": "S", "scan_field": "port", ...}
      },
      "results": {"tx_gbps": 1.2, "pps_actual": 95000, "note": "..."},
      "rtt": 0.984,
      "loss": 0.0,
      "timestamp": "2026-11-20T07:30:00+00:00"
    }

``canonicalize_entry()`` normalizes any free-form entry produced by the LLM:
alias spellings are mapped to canonical names (dst_ip→target_ip,
dport→dst_port, duration_s→duration_ms×1000, packet_size/pktSize→pkt_size,
proto→protocol, ...), measured outcomes mixed into ``params`` are stripped
into ``results``, and anything unrecognized is preserved under
``params.extras`` — no information is dropped.

See docs/experiment_log_schema.md for the full contract.
"""

import json
import os
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

__all__ = [
    "log_tool",
    "canonicalize_entry",
    "canonicalize_params",
    "generate_run_id",
]

# ── Canonical top-level field order ─────────────────────────────────
_TOP_LEVEL_ORDER = (
    "run_id", "iteration", "tool", "params", "results", "rtt", "loss", "timestamp",
)

# ── Alias tables: canonical name → accepted spellings (first match wins) ──
_TARGET_IP_ALIASES = ("target_ip", "dst_ip", "target", "ip", "dest_ip", "dst")
_DST_PORT_ALIASES = ("dst_port", "dport", "port", "dest_port", "target_port")
_PKT_SIZE_ALIASES = ("pkt_size", "packet_size", "pktSize", "packet_len")
_PPS_ALIASES = ("pps", "total_pps")
_RATE_PCT_ALIASES = ("rate",)
_PROTOCOL_ALIASES = ("protocol", "proto")
_DURATION_MS_ALIASES = ("duration_ms",)
_DURATION_S_ALIASES = ("duration_s",)

# Extra-param key normalization: canonical extra name → accepted spellings.
_EXTRA_ALIASES = {
    "tcp_flags": ("tcp_flags", "flags"),
}

# Keys that describe measured outcomes rather than inputs. When found inside
# params they are moved to `results` instead of staying in `params.extras`.
_RESULT_KEYS = frozenset({
    # explicit outcomes recorded by tools or the LLM
    "note", "notes", "status", "success", "error", "elapsed_s", "returncode",
    "tx_gbps", "tx_util", "port_util_pct",
    "pps_actual", "pps_requested", "pps_each", "pps_per_port",
    "achieved_pps", "tx_pps", "payload_b", "frame_b", "static_no_vm",
    # free-form measurement fields invented by the LLM (legacy rows)
    "method", "threads", "conn_per_sec", "bytes_received",
    "dl_bytes", "dl_threads", "dl_err", "dl_conn", "syn_pps", "syn_sent",
    "udp_pkts", "egress_gbps", "combined", "conn", "flood", "pct",
})


def generate_run_id() -> str:
    """Generate a unique run id: ``YYYYmmddTHHMMSS-<hex6>``."""
    return f"{datetime.now().strftime('%Y%m%dT%H%M%S')}-{uuid4().hex[:6]}"


def _pop_first(params: dict, aliases: tuple[str, ...]) -> tuple[str | None, Any]:
    """Pop the first alias present in ``params``; returns (matched_name, value)."""
    for name in aliases:
        if name in params:
            return name, params.pop(name)
    return None, None


def canonicalize_params(params: Any, tool: str | None = None) -> dict[str, Any]:
    """Normalize a free-form ``params`` dict into canonical input parameters.

    Returns a dict with fixed canonical keys (values may be None), plus
    ``extras`` (unrecognized tool-specific params) and ``results``
    (measured outcomes that were mixed into params by the LLM).
    """
    if not isinstance(params, dict):
        return {"extras": {"_raw_params": params}, "results": {}}
    p = dict(params)

    out: dict[str, Any] = {}
    _, out["target_ip"] = _pop_first(p, _TARGET_IP_ALIASES)
    _, out["dst_port"] = _pop_first(p, _DST_PORT_ALIASES)

    # Duration → milliseconds. `duration` (no unit) is intentionally NOT
    # guessed — it stays in extras untouched.
    _, dur_s = _pop_first(p, _DURATION_S_ALIASES)
    _, dur_ms = _pop_first(p, _DURATION_MS_ALIASES)
    if dur_ms is not None:
        out["duration_ms"] = dur_ms
    elif dur_s is not None:
        if isinstance(dur_s, (int, float)) and not isinstance(dur_s, bool):
            out["duration_ms"] = dur_s * 1000
        else:
            out["duration_ms"] = None
            p["duration_s"] = dur_s  # non-numeric: keep verbatim in extras
    else:
        out["duration_ms"] = None

    _, out["pkt_size"] = _pop_first(p, _PKT_SIZE_ALIASES)
    _, out["pps"] = _pop_first(p, _PPS_ALIASES)

    # Pktgen `rate` is a line-rate percentage, NOT packets/s — only map it to
    # rate_pct for pktgen_* tools; a rate seen on other tools stays in extras.
    if tool and tool.startswith("pktgen"):
        _, out["rate_pct"] = _pop_first(p, _RATE_PCT_ALIASES)
    else:
        out["rate_pct"] = None

    _, out["protocol"] = _pop_first(p, _PROTOCOL_ALIASES)

    # Normalize known extra-param spellings.
    for canon, aliases in _EXTRA_ALIASES.items():
        _, value = _pop_first(p, aliases)
        if value is not None:
            p[canon] = value

    # Split measured outcomes out of the remaining params.
    results = {k: p.pop(k) for k in sorted(_RESULT_KEYS & set(p))}

    out["extras"] = p or None
    out["results"] = results
    return out


def canonicalize_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Normalize one free-form log entry into the canonical line schema.

    Injects ``run_id`` (from ``entry``, env ``DSH_RUN_ID``, or ``"unknown"``),
    ``tool`` (from ``entry``, ``params.tool``, or ``"unknown"``) and
    ``timestamp`` (kept verbatim when provided by the caller, e.g. legacy
    migration scripts; otherwise generated now).
    """
    params_raw = entry.get("params")
    tool = entry.get("tool")
    if isinstance(params_raw, dict) and tool is None:
        tool = params_raw.get("tool")

    canon = canonicalize_params(params_raw, tool)

    # Merge measured outcomes stripped from params with explicit results.
    results: dict[str, Any] = {}
    if canon.get("results"):
        results.update(canon["results"])
    if isinstance(entry.get("results"), dict):
        results.update(entry["results"])
    canon.pop("results", None)

    params_out: dict[str, Any] = {}
    for key in ("target_ip", "dst_port", "duration_ms", "pkt_size",
                "pps", "rate_pct", "protocol"):
        params_out[key] = canon.get(key)
    if canon.get("extras"):
        params_out["extras"] = canon["extras"]

    record: dict[str, Any] = {}
    record["run_id"] = entry.get("run_id") or os.environ.get("DSH_RUN_ID") or "unknown"
    if entry.get("iteration") is not None:
        record["iteration"] = entry["iteration"]
    record["tool"] = tool or "unknown"
    record["params"] = params_out
    if results:
        record["results"] = results
    if entry.get("rtt") is not None:
        record["rtt"] = entry["rtt"]
    if entry.get("loss") is not None:
        record["loss"] = entry["loss"]
    record["timestamp"] = entry.get("timestamp") or datetime.now(timezone.utc).isoformat()

    # Fixed field order for readability and diffing; extra keys go last.
    ordered = {k: record[k] for k in _TOP_LEVEL_ORDER if k in record}
    ordered.update({k: v for k, v in record.items() if k not in _TOP_LEVEL_ORDER})
    return ordered


def log_tool(log_path: str, entry: dict[str, Any]) -> dict[str, Any]:
    """Append a canonical experiment entry as a JSONL line to ``log_path``.

    Args:
        log_path: Path to the JSONL file (created if it doesn't exist).
        entry: Free-form dict with keys: params, rtt, loss, and optional
            iteration, tool, results, run_id, timestamp. The entry is
            normalized via :func:`canonicalize_entry` before writing.

    Returns:
        Dict with success status and optional error message.
    """
    # Verify the parent directory exists
    parent = os.path.dirname(os.path.abspath(log_path))
    if parent and not os.path.isdir(parent):
        return {"success": False, "error": f"Directory does not exist: {parent}"}

    record = canonicalize_entry(entry)

    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return {
            "success": True,
            "msg": "日志写入成功",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python log_tool.py <log_path>")
        sys.exit(1)
    result = log_tool(
        sys.argv[1],
        {"params": {"pps": 10}, "rtt": 1.0, "loss": 0.0}
    )
    print(json.dumps(result, indent=2))
