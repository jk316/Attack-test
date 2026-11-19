"""对齐感知的 HTTP 拨测观测构造工具。

在流量工具攻击结束后，把后台 HttpMonitor 采集的 HTTP 探测样本组织成对
LLM 友好的结构。攻击窗口 ``attack_window`` 由 ``build_rtt_observation`` 提供
（两者共享同一 ``t0``/``t_end``），此处只返回 HTTP 专有字段，避免 key 冲突。

指标语义：
- ``success_rate``：拿到 HTTP 响应（任意状态码）的比例 —— 反映连接/可用性。
- ``five_xx_rate``：5xx 占总请求的比例 —— 反映服务器过载/应用层故障。
- ``avg_ttfb_ms`` / ``avg_total_ms``：首字节/总响应时间 —— 反映业务延迟退化。
- ``timeout_count`` / ``connection_error_count``：连接层失败类型计数。
"""

from __future__ import annotations

import time
from typing import Any

MIN_MEANINGFUL_WINDOW_S = 1.0


def _fmt(ts: float) -> dict[str, Any]:
    """把 epoch 秒格式化为双格式：数值 + 人类可读本地时间字符串。"""
    return {
        "ts": round(ts, 3),
        "iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)),
    }


def build_http_observation(monitor: Any, t0: float, mode: str) -> dict[str, Any]:
    """构造对齐感知的 HTTP 拨测观测结果。

    Args:
        monitor: HttpMonitor 实例（需支持 ``is_running()`` 与
                 ``get_samples_since(t0)``）。
        t0: 攻击开始时间戳（``time.time()`` epoch 秒）。
        mode: 攻击执行模式，如 ``"scapy"`` / ``"live"`` / ``"dry_run"``。

    Returns:
        ``{"http_during": ..., "http_observation_window": ...}``，供调用方
        ``result.update(...)`` 合并。``http_during`` 在 monitor 未运行/无样本
        时为 ``None``。
    """
    if not _monitor_running(monitor):
        return {
            "http_during": None,
            "http_observation_window": {
                "sample_count": 0,
                "first_sample": None,
                "last_sample": None,
                "covers_attack_window": False,
                "note": "HTTP monitor 未运行——无 HTTP 观测，请先调用 "
                        "start_http_monitor，本结果不可用于规划。",
            },
        }

    samples = _safe_samples(monitor, t0)
    sample_count = len(samples)

    http_observation_window: dict[str, Any] = {
        "sample_count": sample_count,
        "first_sample": _fmt(samples[0]["ts"]) if sample_count else None,
        "last_sample": _fmt(samples[-1]["ts"]) if sample_count else None,
        "covers_attack_window": False,
        "note": "",
    }

    if sample_count == 0:
        http_observation_window["note"] = (
            "观测窗口内无 HTTP 探测结果——攻击时长过短或目标无回应，"
            "此结果不可用于规划，建议增大 duration 或重跑本轮。"
        )
        return {
            "http_during": None,
            "http_observation_window": http_observation_window,
        }

    total = sample_count
    success_count = sum(1 for s in samples if s.get("success"))
    timeout_count = sum(1 for s in samples if s.get("error_type") == "timeout")
    connection_error_count = sum(1 for s in samples if s.get("error_type") == "connection_refused")

    ttfb_values = [s["ttfb_ms"] for s in samples if s.get("ttfb_ms") is not None]
    total_values = [s["total_ms"] for s in samples if s.get("total_ms") is not None]

    status_codes: dict[int, int] = {}
    for s in samples:
        code = s.get("status_code")
        if code is not None:
            status_codes[int(code)] = status_codes.get(int(code), 0) + 1

    five_xx = sum(c for code, c in status_codes.items() if code >= 500)

    http_during = {
        "total_requests": total,
        "success_count": success_count,
        "success_rate": round(success_count / total, 3),
        "timeout_count": timeout_count,
        "connection_error_count": connection_error_count,
        "avg_ttfb_ms": round(sum(ttfb_values) / len(ttfb_values), 3) if ttfb_values else None,
        "max_ttfb_ms": round(max(ttfb_values), 3) if ttfb_values else None,
        "avg_total_ms": round(sum(total_values) / len(total_values), 3) if total_values else None,
        "status_codes": status_codes,
        "five_xx_rate": round(five_xx / total, 3),
    }

    duration_s = round(time.time() - t0, 3)
    if duration_s < MIN_MEANINGFUL_WINDOW_S:
        http_observation_window["covers_attack_window"] = False
        http_observation_window["note"] = (
            f"攻击窗口过短（{duration_s}s < {MIN_MEANINGFUL_WINDOW_S}s）——"
            f"仅采到 {total} 个 HTTP 探测，可能不足以反映攻击效果。"
        )
    else:
        http_observation_window["covers_attack_window"] = True
        note = f"观测窗口已覆盖攻击窗口，共 {total} 个 HTTP 请求（成功 {success_count}）。"
        if five_xx:
            note += f" 出现 {five_xx} 个 5xx——服务器可能已过载。"
        if timeout_count or connection_error_count:
            note += f" 连接层失败 {timeout_count + connection_error_count} 次。"
        http_observation_window["note"] = note

    return {
        "http_during": http_during,
        "http_observation_window": http_observation_window,
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
