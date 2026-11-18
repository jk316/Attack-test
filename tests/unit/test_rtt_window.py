"""Unit tests for src/tools/rtt_window.py — 对齐感知的 RTT 观测构造。"""

import time
from unittest.mock import MagicMock

import pytest

from src.tools.rtt_window import build_rtt_observation, MIN_MEANINGFUL_WINDOW_S

pytestmark = pytest.mark.unit


def _make_monitor(running=True, samples=None):
    m = MagicMock()
    m.is_running.return_value = running
    m.get_samples_since.return_value = samples if samples is not None else []
    return m


class TestAttackWindow:
    """attack_window 时间点结构。"""

    def test_attack_window_has_dual_format_and_mode(self):
        t0 = time.time() - 5.0
        monitor = _make_monitor(samples=[{"ts": t0 + 1, "rtt_ms": 10.0}])

        result = build_rtt_observation(monitor, t0, mode="scapy")

        aw = result["attack_window"]
        assert aw["mode"] == "scapy"
        # 双格式：epoch ts + 可读 iso
        assert isinstance(aw["start"]["ts"], float)
        assert isinstance(aw["start"]["iso"], str)
        assert isinstance(aw["end"]["ts"], float)
        assert aw["duration_s"] >= 5.0
        # end 应晚于 start
        assert aw["end"]["ts"] >= aw["start"]["ts"]


class TestCoversAttackWindow:
    """观测覆盖诊断。"""

    def test_covers_true_when_window_long_enough_and_samples_present(self):
        t0 = time.time() - 5.0
        monitor = _make_monitor(samples=[
            {"ts": t0 + 1, "rtt_ms": 10.0, "sent": 1, "received": 1},
            {"ts": t0 + 3, "rtt_ms": 20.0, "sent": 1, "received": 1},
        ])

        result = build_rtt_observation(monitor, t0, mode="live")

        ow = result["observation_window"]
        assert ow["covers_attack_window"] is True
        assert ow["sample_count"] == 2
        assert result["rtt_during"]["avg_rtt_ms"] == 15.0
        assert result["rtt_during"]["loss_pct"] == 0.0
        assert result["rtt_during"]["total_sent"] == 2
        assert result["rtt_during"]["total_received"] == 2
        assert "覆盖" in ow["note"]

    def test_short_window_flags_misalignment_even_with_samples(self):
        """duration=0 / dry-run 场景：窗口过短，即便有样本也应告警。

        契约不变式：rtt_during != null ⇒ covers_attack_window == true——
        未覆盖的观测不得携带可被误用的聚合数据，故 rtt_during 为 null。
        """
        t0 = time.time()  # 窗口 ≈ 0s
        monitor = _make_monitor(samples=[{"ts": t0, "rtt_ms": 12.0}])

        result = build_rtt_observation(monitor, t0, mode="dry_run")

        ow = result["observation_window"]
        assert result["attack_window"]["duration_s"] < MIN_MEANINGFUL_WINDOW_S
        assert ow["covers_attack_window"] is False
        assert "过短" in ow["note"]
        assert result["rtt_during"] is None  # 不变式（contracts/rtt-observation.md §5）


class TestNoObservation:
    """无观测数据的分支。"""

    def test_no_samples_returns_none_and_warns(self):
        t0 = time.time() - 5.0
        monitor = _make_monitor(samples=[])

        result = build_rtt_observation(monitor, t0, mode="live")

        assert result["rtt_during"] is None
        assert result["observation_window"]["sample_count"] == 0
        assert result["observation_window"]["covers_attack_window"] is False
        assert "无 ping 探测结果" in result["observation_window"]["note"]
        # 攻击窗口仍应暴露（用于诊断）
        assert result["attack_window"]["duration_s"] >= 5.0

    def test_monitor_not_running_returns_none_and_warns(self):
        t0 = time.time() - 5.0
        monitor = _make_monitor(running=False)

        result = build_rtt_observation(monitor, t0, mode="scapy")

        assert result["rtt_during"] is None
        assert result["observation_window"]["covers_attack_window"] is False
        assert "monitor 未运行" in result["observation_window"]["note"]

    def test_exception_in_monitor_is_safe(self):
        """monitor 抛异常时不应中断，视为无观测。"""
        t0 = time.time() - 5.0
        monitor = MagicMock()
        monitor.is_running.side_effect = RuntimeError("boom")

        result = build_rtt_observation(monitor, t0, mode="live")

        assert result["rtt_during"] is None
        assert result["observation_window"]["covers_attack_window"] is False


class TestLossPct:
    """丢包率相关测试。"""

    def test_partial_loss(self):
        """部分丢包时 loss_pct 应在 rtt_during 和 observation_window 中反映。"""
        t0 = time.time() - 5.0
        monitor = _make_monitor(samples=[
            {"ts": t0 + 1, "rtt_ms": 10.0, "sent": 1, "received": 1},
            {"ts": t0 + 2, "rtt_ms": None, "sent": 1, "received": 0},
            {"ts": t0 + 3, "rtt_ms": 20.0, "sent": 1, "received": 1},
            {"ts": t0 + 4, "rtt_ms": None, "sent": 1, "received": 0},
        ])

        result = build_rtt_observation(monitor, t0, mode="live")

        rd = result["rtt_during"]
        assert rd["avg_rtt_ms"] == 15.0
        assert rd["loss_pct"] == 50.0
        assert rd["total_sent"] == 4
        assert rd["total_received"] == 2

    def test_all_lost(self):
        """全丢包时 rtt_during 应为 None，note 提示目标不可达。"""
        t0 = time.time() - 5.0
        monitor = _make_monitor(samples=[
            {"ts": t0 + 1, "rtt_ms": None, "sent": 1, "received": 0},
            {"ts": t0 + 2, "rtt_ms": None, "sent": 1, "received": 0},
        ])

        result = build_rtt_observation(monitor, t0, mode="live")

        assert result["rtt_during"] is None
        assert "均丢失" in result["observation_window"]["note"]
        assert result["observation_window"]["covers_attack_window"] is False

    def test_high_loss_generates_warning(self):
        """高丢包率(>=50%) 时 note 应包含丢包严重提示。"""
        t0 = time.time() - 5.0
        monitor = _make_monitor(samples=[
            {"ts": t0 + 1, "rtt_ms": 10.0, "sent": 1, "received": 1},
            {"ts": t0 + 2, "rtt_ms": None, "sent": 1, "received": 0},
            {"ts": t0 + 3, "rtt_ms": None, "sent": 1, "received": 0},
        ])

        result = build_rtt_observation(monitor, t0, mode="live")

        assert result["observation_window"]["covers_attack_window"] is True
        assert result["rtt_during"]["loss_pct"] >= 50.0
        assert "丢包严重" in result["observation_window"]["note"]


class TestFiveClassCoverage:
    """T012：五类 covers 判定（G-005，对照 contracts/rtt-observation.md §5）。"""

    def test_class_not_running(self):
        t0 = time.time() - 5.0
        result = build_rtt_observation(_make_monitor(running=False), t0,
                                       mode="scapy")
        ow = result["observation_window"]
        assert result["rtt_during"] is None
        assert ow["covers_attack_window"] is False
        assert "先调用 start_ping_monitor" in ow["note"]
        assert "不可用于规划" in ow["note"]

    def test_class_no_samples(self):
        t0 = time.time() - 5.0
        result = build_rtt_observation(_make_monitor(samples=[]), t0, mode="scapy")
        ow = result["observation_window"]
        assert result["rtt_during"] is None
        assert ow["covers_attack_window"] is False
        assert ("增大 duration" in ow["note"] or "无 ping 探测结果" in ow["note"])

    def test_class_all_lost(self):
        t0 = time.time() - 5.0
        samples = [{"ts": t0 + 1, "rtt_ms": None, "sent": 1, "received": 0}] * 3
        result = build_rtt_observation(_make_monitor(samples=samples), t0,
                                       mode="scapy")
        ow = result["observation_window"]
        assert result["rtt_during"] is None
        assert ow["covers_attack_window"] is False
        assert "均丢失" in ow["note"]

    def test_class_short_window(self):
        t0 = time.time()
        samples = [{"ts": t0, "rtt_ms": 5.0, "sent": 1, "received": 1}]
        result = build_rtt_observation(_make_monitor(samples=samples), t0,
                                       mode="dry_run")
        ow = result["observation_window"]
        assert ow["covers_attack_window"] is False
        assert "过短" in ow["note"]
        assert result["rtt_during"] is None  # 不变式

    def test_class_normal_cover(self):
        t0 = time.time() - 5.0
        samples = [
            {"ts": t0 + 1, "rtt_ms": 4.0, "sent": 1, "received": 1},
            {"ts": t0 + 2, "rtt_ms": 8.0, "sent": 1, "received": 1},
            {"ts": t0 + 3, "rtt_ms": None, "sent": 1, "received": 0},
        ]
        result = build_rtt_observation(_make_monitor(samples=samples), t0,
                                       mode="scapy")
        ow = result["observation_window"]
        assert ow["covers_attack_window"] is True
        assert result["rtt_during"] is not None
        assert "覆盖" in ow["note"]

    def test_class_normal_cover_high_loss_appends_signal(self):
        t0 = time.time() - 5.0
        samples = [
            {"ts": t0 + 1, "rtt_ms": 4.0, "sent": 1, "received": 1},
            {"ts": t0 + 2, "rtt_ms": None, "sent": 1, "received": 0},
            {"ts": t0 + 3, "rtt_ms": None, "sent": 1, "received": 0},
        ]
        result = build_rtt_observation(_make_monitor(samples=samples), t0,
                                       mode="scapy")
        assert result["observation_window"]["covers_attack_window"] is True
        assert "丢包严重" in result["observation_window"]["note"]


class TestRttDuringAggregation:
    """T013：rtt_during 聚合口径与不变式（contracts/rtt-observation.md §4/§5）。"""

    def test_weighted_aggregation_matches_manual(self):
        t0 = time.time() - 5.0
        # fping_q 风格加权样本：cycle(10 sent, 8 recv, avg 5.0) + 单探测(1/1, 20.0)
        samples = [
            {"ts": t0 + 1, "rtt_ms": 5.0, "sent": 10, "received": 8},
            {"ts": t0 + 2, "rtt_ms": 20.0, "sent": 1, "received": 1},
        ]
        result = build_rtt_observation(_make_monitor(samples=samples), t0,
                                       mode="scapy")
        rd = result["rtt_during"]
        assert rd["avg_rtt_ms"] == round((5.0 * 8 + 20.0 * 1) / 9, 3)
        assert rd["min_rtt_ms"] == 5.0
        assert rd["max_rtt_ms"] == 20.0
        assert rd["loss_pct"] == round((1 - 9 / 11) * 100, 1)
        assert rd["total_sent"] == 11
        assert rd["total_received"] == 9

    def test_invariant_non_null_implies_covered(self):
        """不变式：rtt_during != null ⇒ covers_attack_window == true。"""
        t0_long = time.time() - 5.0
        good = build_rtt_observation(_make_monitor(samples=[
            {"ts": t0_long + 1, "rtt_ms": 10.0}]), t0_long, mode="scapy")
        if good["rtt_during"] is not None:
            assert good["observation_window"]["covers_attack_window"] is True

        # 反例：未覆盖的各类观测 rtt_during 必须为 null
        not_running = build_rtt_observation(_make_monitor(running=False),
                                            t0_long, mode="scapy")
        assert not_running["rtt_during"] is None
        no_samples = build_rtt_observation(_make_monitor(samples=[]),
                                           t0_long, mode="scapy")
        assert no_samples["rtt_during"] is None
        all_lost = build_rtt_observation(_make_monitor(samples=[
            {"ts": t0_long + 1, "rtt_ms": None, "sent": 1, "received": 0}]),
            t0_long, mode="scapy")
        assert all_lost["rtt_during"] is None
        short = build_rtt_observation(_make_monitor(samples=[
            {"ts": time.time(), "rtt_ms": 10.0}]), time.time(), mode="dry_run")
        assert short["rtt_during"] is None

    def test_window_timepoints_correct(self):
        t0 = time.time() - 5.0
        first_ts, last_ts = t0 + 1, t0 + 4
        samples = [
            {"ts": first_ts, "rtt_ms": 1.0, "sent": 1, "received": 1},
            {"ts": last_ts, "rtt_ms": 2.0, "sent": 1, "received": 1},
        ]
        result = build_rtt_observation(_make_monitor(samples=samples), t0,
                                       mode="scapy")
        aw, ow = result["attack_window"], result["observation_window"]
        assert aw["start"]["ts"] == round(t0, 3)
        assert aw["end"]["ts"] >= aw["start"]["ts"]
        assert aw["mode"] == "scapy"
        # 两端点各自取整后再相减可能有 ±0.001 舍入差，用容差断言
        assert abs(aw["duration_s"] - (aw["end"]["ts"] - aw["start"]["ts"])) < 0.002
        assert ow["first_sample"]["ts"] == round(first_ts, 3)
        assert ow["last_sample"]["ts"] == round(last_ts, 3)
