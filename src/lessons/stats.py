"""Deterministic rule-based statistics for a single run's jsonl rows.

Pure functions only — no network, no LLM, no filesystem. These produce the
"rule skeleton" of a lesson document and are the fallback facts the LLM
narrative is built on (spec 010 FR-003).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

# ── Composite-score weights (documented; deterministic) ─────────────
# Higher loss dominates (primary degradation signal), then RTT, then HTTP
# business degradation (success-rate drop and TTFB rise).
_LOSS_WEIGHT = 10.0
_RTT_WEIGHT = 1.0
_HTTP_FAIL_WEIGHT = 100.0
_TTFB_WEIGHT = 1.0

# Absolute RTT delta (ms) below which first-vs-last is considered "平稳".
_TREND_EPSILON = 1.0


@dataclass(frozen=True)
class IterationObservation:
    iteration: int | None
    tool: str
    target_ip: str | None
    key_params: str
    rtt: float | None
    loss: float | None
    http_success_rate: float | None
    http_ttfb_ms: float | None

    @property
    def has_observation(self) -> bool:
        return (
            self.rtt is not None
            or self.loss is not None
            or self.http_success_rate is not None
            or self.http_ttfb_ms is not None
        )


@dataclass(frozen=True)
class RunStats:
    observations: tuple[IterationObservation, ...]
    best: IterationObservation | None
    best_score: float | None
    trend: str  # 上升 / 下降 / 平稳 / 无数据
    converged: str  # 可能已收敛 / 未收敛 / 无数据
    tool_counts: dict[str, int]


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _lookup(row: dict, *keys: str) -> Any:
    """Return the first present value across results → params → params.extras."""
    results = row.get("results")
    params = row.get("params")
    if isinstance(results, dict):
        for key in keys:
            if results.get(key) is not None:
                return results[key]
    if isinstance(params, dict):
        for key in keys:
            if params.get(key) is not None:
                return params[key]
        extras = params.get("extras")
        if isinstance(extras, dict):
            for key in keys:
                if extras.get(key) is not None:
                    return extras[key]
    return None


def _http_success_rate(row: dict) -> float | None:
    return _to_float(_lookup(row, "success_rate"))


def _http_ttfb(row: dict) -> float | None:
    return _to_float(_lookup(row, "avg_ttfb_ms", "ttfb_ms"))


def _key_params(params: dict) -> str:
    """Compact human-readable summary of the key attack parameters."""
    if not isinstance(params, dict):
        return ""
    parts: list[str] = []
    if params.get("pps") is not None:
        parts.append(f"pps={params['pps']}")
    if params.get("rate_pct") is not None:
        parts.append(f"rate={params['rate_pct']}%")
    if params.get("duration_ms") is not None:
        parts.append(f"dur={params['duration_ms']}ms")
    if params.get("pkt_size") is not None:
        parts.append(f"size={params['pkt_size']}")
    if params.get("dst_port") is not None:
        parts.append(f"port={params['dst_port']}")
    if params.get("protocol"):
        parts.append(f"proto={params['protocol']}")
    return ", ".join(parts)


def _score(obs: IterationObservation) -> float | None:
    score = 0.0
    has_any = False
    if obs.loss is not None:
        score += obs.loss * _LOSS_WEIGHT
        has_any = True
    if obs.rtt is not None:
        score += obs.rtt * _RTT_WEIGHT
        has_any = True
    if obs.http_success_rate is not None:
        rate = max(0.0, min(1.0, obs.http_success_rate))
        score += (1.0 - rate) * _HTTP_FAIL_WEIGHT
        has_any = True
    if obs.http_ttfb_ms is not None:
        score += obs.http_ttfb_ms * _TTFB_WEIGHT
        has_any = True
    return score if has_any else None


def _trend(rtts: list[float]) -> str:
    if len(rtts) < 2:
        return "无数据"
    delta = rtts[-1] - rtts[0]
    if delta > _TREND_EPSILON:
        return "上升"
    if delta < -_TREND_EPSILON:
        return "下降"
    return "平稳"


def _convergence(rtts: list[float]) -> str:
    if len(rtts) < 2:
        return "无数据"
    last = rtts[-1]
    if last > max(rtts[:-1]):
        return "未收敛"
    return "可能已收敛"


def summarize_run(rows: list[dict] | tuple[dict, ...]) -> RunStats:
    """Compute the rule-based stats for one run's rows (in iteration order)."""
    observations: list[IterationObservation] = []
    rtts: list[float] = []

    for row in rows:
        params = row.get("params") if isinstance(row.get("params"), dict) else {}
        tool = row.get("tool") or params.get("tool") or "unknown"
        rtt = _to_float(row.get("rtt"))
        loss = _to_float(row.get("loss"))
        if rtt is not None:
            rtts.append(rtt)

        observations.append(
            IterationObservation(
                iteration=row.get("iteration"),
                tool=str(tool),
                target_ip=params.get("target_ip"),
                key_params=_key_params(params),
                rtt=rtt,
                loss=loss,
                http_success_rate=_http_success_rate(row),
                http_ttfb_ms=_http_ttfb(row),
            )
        )

    scored = [(obs, _score(obs)) for obs in observations]
    scored_with_obs = [(obs, s) for obs, s in scored if s is not None]
    if scored_with_obs:
        best, best_score = max(scored_with_obs, key=lambda pair: pair[1])
    else:
        best, best_score = None, None

    return RunStats(
        observations=tuple(observations),
        best=best,
        best_score=best_score,
        trend=_trend(rtts),
        converged=_convergence(rtts),
        tool_counts=dict(Counter(obs.tool for obs in observations)),
    )
