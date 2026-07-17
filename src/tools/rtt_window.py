"""对齐感知的 RTT 观测构造工具。

在流量工具（Scapy / Pktgen）攻击结束后，把后台 PingMonitor 采集的 RTT
样本组织成对 LLM 友好的结构，并**显式暴露攻击窗口与观测窗口的时间点**，
让 LLM 能判断本轮观测是否真正落在攻击进行期间。

设计要点：
- 攻击起点 ``t0`` 与样本 ``ts`` 均来自 ``time.time()``（见 ping_monitor.py），
  时钟一致，可直接比较，无 wall/monotonic 混用问题。
- ``rtt_during`` 保持历史结构（samples / avg / min / max_rtt_ms）向后兼容。
- ``attack_window`` / ``observation_window`` 为新增字段，携带对齐诊断。
"""

from __future__ import annotations

import time
from typing import Any

# 攻击窗口短于此阈值（秒）时，认为采样不足以反映攻击效果。
# 典型触发场景：duration=0（forever，不 sleep）或 dry-run（不发流）。
MIN_MEANINGFUL_WINDOW_S = 1.0


def _fmt(ts: float) -> dict[str, Any]:
    """把 epoch 秒格式化为双格式：数值 + 人类可读本地时间字符串。"""
    return {
        "ts": round(ts, 3),
        "iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)),
    }


def build_rtt_observation(monitor: Any, t0: float, mode: str) -> dict[str, Any]:
    """构造对齐感知的 RTT 观测结果。

    Args:
        monitor: PingMonitor 实例（需支持 ``is_running()`` 与
                 ``get_samples_since(t0)``）。
        t0: 攻击开始时间戳（``time.time()`` epoch 秒）。
        mode: 攻击执行模式，用于结果标注，例如 ``"scapy"`` / ``"live"`` /
              ``"dry_run"``。

    Returns:
        含三个键的 dict，供调用方 ``result.update(...)`` 合并：

        - ``rtt_during``: ``{samples, avg_rtt_ms, min_rtt_ms, max_rtt_ms}``
          或 ``None``（monitor 未运行 / 无样本 / 异常）。结构与历史一致。
        - ``attack_window``: ``{start, end, duration_s, mode}``，
          ``start`` / ``end`` 为 ``{ts, iso}`` 双格式时间点。
        - ``observation_window``: ``{sample_count, first_sample, last_sample,
          covers_attack_window, note}`` —— 对齐诊断。
    """
    t_end = time.time()
    duration_s = round(t_end - t0, 3)
    attack_window = {
        "start": _fmt(t0),
        "end": _fmt(t_end),
        "duration_s": duration_s,
        "mode": mode,
    }

    # monitor 未运行：没有任何观测数据可用。
    if not _monitor_running(monitor):
        return {
            "rtt_during": None,
            "attack_window": attack_window,
            "observation_window": {
                "sample_count": 0,
                "first_sample": None,
                "last_sample": None,
                "covers_attack_window": False,
                "note": "ping monitor 未运行——无 RTT 观测，请先调用 "
                        "start_ping_monitor，本结果不可用于规划。",
            },
        }

    samples = _safe_samples(monitor, t0)
    sample_count = len(samples)

    observation_window: dict[str, Any] = {
        "sample_count": sample_count,
        "first_sample": _fmt(samples[0]["ts"]) if sample_count else None,
        "last_sample": _fmt(samples[-1]["ts"]) if sample_count else None,
        "covers_attack_window": False,
        "note": "",
    }

    if sample_count == 0:
        observation_window["note"] = (
            "观测窗口内无 ping 探测结果——攻击时长过短或目标无回应，"
            "此结果不可用于规划，建议增大 duration 或重跑本轮。"
        )
        return {
            "rtt_during": None,
            "attack_window": attack_window,
            "observation_window": observation_window,
        }

    # Compute per-probe stats: sent / received / RTT / loss
    total_sent = sum(s.get("sent", 1) for s in samples)
    total_received = sum(s.get("received", 1) for s in samples)
    loss_pct = round((1 - total_received / total_sent) * 100, 1) if total_sent > 0 else 0.0

    # RTT stats from received probes only (rtt_ms is None for lost probes).
    # Weighted by received count so fping_q cycles (>1 probe each) aren't
    # under-weighted relative to per-probe backends.
    rtt_values: list[float] = []
    rtt_weighted_sum = 0.0
    rtt_weight_total = 0
    for s in samples:
        received = s.get("received", 1)
        rtt = s.get("rtt_ms")
        if received > 0 and rtt is not None:
            rtt_values.append(rtt)
            rtt_weighted_sum += rtt * received
            rtt_weight_total += received

    if not rtt_values:
        observation_window["note"] = (
            f"观测窗口内所有 {total_sent} 个探测均丢失（loss={loss_pct}%）。"
            "目标可能不可达或攻击完全阻断了 ICMP 通信。"
        )
        return {
            "rtt_during": None,
            "attack_window": attack_window,
            "observation_window": observation_window,
        }

    rtt_during = {
        "samples": samples,
        "avg_rtt_ms": round(rtt_weighted_sum / rtt_weight_total, 3) if rtt_weight_total > 0 else 0.0,
        "min_rtt_ms": round(min(rtt_values), 3),
        "max_rtt_ms": round(max(rtt_values), 3),
        "loss_pct": loss_pct,
        "total_sent": total_sent,
        "total_received": total_received,
    }

    # 有样本，但攻击窗口过短（forever 未等待 / dry-run 未发流）时告警：
    # 样本虽存在，却可能只覆盖了攻击刚开始的一瞬。
    if duration_s < MIN_MEANINGFUL_WINDOW_S:
        observation_window["covers_attack_window"] = False
        observation_window["note"] = (
            f"攻击窗口过短（{duration_s}s < {MIN_MEANINGFUL_WINDOW_S}s）——"
            "工具未等待攻击完成（如 duration=0 或 dry-run），"
            f"仅采到 {total_sent} 个探测（收到 {total_received}），可能不足以反映攻击效果。"
        )
    else:
        observation_window["covers_attack_window"] = True
        note = f"观测窗口已覆盖攻击窗口，共 {total_sent} 个探测（收到 {total_received}，丢包 {loss_pct}%）。"
        if loss_pct >= 50.0:
            note += " 丢包严重——这本身就是有效攻击信号（DoS/DDoS 效果）。"
        observation_window["note"] = note

    return {
        "rtt_during": rtt_during,
        "attack_window": attack_window,
        "observation_window": observation_window,
    }


def _monitor_running(monitor: Any) -> bool:
    """安全判断 monitor 是否在运行（异常视为未运行）。"""
    try:
        return bool(monitor.is_running())
    except Exception:
        return False


def _safe_samples(monitor: Any, t0: float) -> list[dict[str, Any]]:
    """安全获取 t0 之后的样本（异常返回空列表）。"""
    try:
        return monitor.get_samples_since(t0) or []
    except Exception:
        return []
