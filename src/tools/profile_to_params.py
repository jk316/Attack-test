"""确定性画像 → 初始流量参数映射（004-G-004，contracts/pcap-profile.md §2）。

纯函数、无 I/O；映射输出仅是流量工具的输入候选，流量工具内部仍执行
allowlist / 参数上限钳制 / HITL 三重门禁（契约安全不变式）。
"""
from __future__ import annotations

from typing import Any

from src.tools.traffic_send_tool import (
    MAX_PPS,
    MAX_DURATION_S,
    MAX_PACKET_SIZE,
    MAX_FLOW_COUNT,
)

# 配置默认的兜底值（调用方应传入配置链默认覆盖，见 contracts §2 回落语义）
BUILTIN_DEFAULTS = {
    "dst_port": 8080,
    "packet_size": 64,
    "pps": 100,
    "flow_count": 1,
    "duration_s": 10,
}

# 直方图桶的确定性累加顺序（契约 §3 示例：64 → 128 → 256 → 512 → 1024 → other）
_BUCKET_ORDER = ("64", "128", "256", "512", "1024", "other")


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(value, hi))


def profile_to_params(profile: dict, defaults: dict | None = None) -> dict:
    """把画像 JSON 确定性映射为初始流量参数（contracts/pcap-profile.md §2）。

    Args:
        profile: 画像（pcap_profile_tool 输出结构）。
        defaults: 配置默认值 dict（dst_port / packet_size / pps /
            flow_count / duration_s），缺省用 BUILTIN_DEFAULTS。

    Returns:
        {"dst_port", "packet_size", "flow_count", "pps", "duration_s"}。
    """
    d = {**BUILTIN_DEFAULTS, **(defaults or {})}

    # dst_port ← top_dst_ports[0]（空排行回落默认，钳制 1–65535）
    ports = profile.get("top_dst_ports") or []
    dst_port = ports[0] if ports else d["dst_port"]
    dst_port = int(_clamp(int(dst_port), 1, 65535))

    # packet_size ← 概率累计 ≥ 50% 的首个桶（中位数桶）
    hist = profile.get("packet_size_hist")
    hist = hist if isinstance(hist, dict) else {}
    packet_size: int | None = None
    acc = 0.0
    for bucket in _BUCKET_ORDER:
        acc += float(hist.get(bucket, 0.0) or 0.0)
        if acc >= 0.5:
            packet_size = 1024 if bucket == "other" else int(bucket)
            break
    if packet_size is None:
        packet_size = int(d["packet_size"])
    packet_size = int(_clamp(packet_size, 1, MAX_PACKET_SIZE))

    # flow_count ← approx_flow_count，clamp [1, MAX_FLOW_COUNT]
    flow_stats = profile.get("flow_stats")
    approx = (flow_stats or {}).get("approx_flow_count", 0) \
        if isinstance(flow_stats, dict) else 0
    try:
        approx = int(approx)
    except (TypeError, ValueError):
        approx = int(d["flow_count"])
    flow_count = int(_clamp(approx if approx > 0 else int(d["flow_count"]),
                            1, MAX_FLOW_COUNT))

    # pps ← 1000 / iat_ms_stats.mean（mean ≤ 0 或无 IAT 回落默认，钳制 [1, MAX_PPS]）
    iat = profile.get("iat_ms_stats")
    iat = iat if isinstance(iat, dict) else {}
    mean = float(iat.get("mean", 0.0) or 0.0)
    if mean > 0:
        pps = int(round(1000.0 / mean))
    else:
        pps = int(d["pps"])
    pps = int(_clamp(pps, 1, MAX_PPS))

    # duration_s ← 维持配置默认（画像不约束时长），钳制 [1, MAX_DURATION_S]
    duration_s = int(_clamp(int(d["duration_s"]), 1, MAX_DURATION_S))

    return {
        "dst_port": dst_port,
        "packet_size": packet_size,
        "flow_count": flow_count,
        "pps": pps,
        "duration_s": duration_s,
    }
