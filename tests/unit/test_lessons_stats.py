"""Tests for src/lessons/stats.py — deterministic rule-based statistics."""

from src.lessons.stats import summarize_run


def _row(iteration, tool="traffic_send", rtt=None, loss=None,
         results=None, params=None):
    row = {
        "run_id": "20261125T070649-9e1fe6",
        "iteration": iteration,
        "tool": tool,
        "rtt": rtt,
        "loss": loss,
    }
    if results is not None:
        row["results"] = results
    row["params"] = params if params is not None else {}
    return row


def test_best_iteration_and_trend():
    rows = [
        _row(1, rtt=1.2, loss=0.0),
        _row(2, rtt=0.9, loss=0.0),
        _row(3, rtt=0.9, loss=0.0),
        _row(4, rtt=32.78, loss=32.3),
        _row(5, rtt=167.0, loss=33.3),
    ]
    stats = summarize_run(rows)

    assert stats.best.iteration == 5
    assert stats.trend == "上升"
    assert stats.converged == "未收敛"
    assert stats.tool_counts == {"traffic_send": 5}


def test_no_observation_rows_not_best():
    rows = [
        _row(1, rtt=5.0),
        _row(2),
        _row(3, rtt=1.0),
    ]
    stats = summarize_run(rows)

    assert stats.best.iteration == 1
    assert not stats.observations[1].has_observation


def test_http_degradation_included():
    rows = [
        _row(1, results={"success_rate": 0.714, "avg_ttfb_ms": 605.0}),
        _row(2, rtt=10.0),
    ]
    stats = summarize_run(rows)

    # row1 score = (1-0.714)*100 + 605 = 633.6; row2 score = 10
    assert stats.best.iteration == 1
    assert stats.observations[0].http_success_rate == 0.714
    assert stats.observations[0].http_ttfb_ms == 605.0


def test_trend_down_and_converged():
    rows = [_row(1, rtt=10.0), _row(2, rtt=5.0)]
    stats = summarize_run(rows)
    assert stats.trend == "下降"
    assert stats.converged == "可能已收敛"


def test_trend_no_data():
    rows = [_row(1), _row(2)]
    stats = summarize_run(rows)
    assert stats.trend == "无数据"
    assert stats.converged == "无数据"
    assert stats.best is None
    assert stats.best_score is None


def test_key_params_summary():
    rows = [
        _row(1, params={"target_ip": "10.0.0.1", "pps": 100,
                        "duration_ms": 5000, "pkt_size": 64, "protocol": "udp"}),
    ]
    stats = summarize_run(rows)
    key = stats.observations[0].key_params
    assert "pps=100" in key
    assert "dur=5000ms" in key
    assert "size=64" in key
    assert "proto=udp" in key
