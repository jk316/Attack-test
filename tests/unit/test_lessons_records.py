"""Tests for src/lessons/records.py — grouping, filtering, ordering."""

import json

from src.lessons.records import load_runs


def _write(path, rows):
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_groups_and_orders_by_run_id(tmp_path):
    log = tmp_path / "exp.jsonl"
    _write(log, [
        {"run_id": "20261125T070649-9e1fe6", "iteration": 2,
         "timestamp": "2026-11-25T07:06:52+00:00", "tool": "traffic_send",
         "params": {"target_ip": "10.0.0.1"}, "rtt": 1.0},
        {"run_id": "20261125T070649-9e1fe6", "iteration": 1,
         "timestamp": "2026-11-25T07:06:50+00:00", "tool": "traffic_send",
         "params": {"target_ip": "10.0.0.1"}, "rtt": 0.9},
        {"run_id": "20261124T012512-14e27c", "iteration": 1,
         "timestamp": "2026-11-24T01:25:12+00:00", "tool": "pktgen_udp_flood",
         "params": {"target_ip": "10.0.0.2"}, "rtt": 2.0},
    ])

    result = load_runs(log)
    assert [run.run_id for run in result.runs] == [
        "20261124T012512-14e27c",
        "20261125T070649-9e1fe6",
    ]

    run = result.runs[1]
    assert [row["iteration"] for row in run.rows] == [1, 2]
    assert run.target_ip == "10.0.0.1"
    assert run.iterations == 2
    assert run.start_ts == "2026-11-25T07:06:50+00:00"
    assert run.end_ts == "2026-11-25T07:06:52+00:00"


def test_skips_unknown_and_legacy(tmp_path):
    log = tmp_path / "exp.jsonl"
    _write(log, [
        {"run_id": "unknown", "iteration": 1},
        {"run_id": "legacy-20261120T073000-01", "iteration": 1},
        {"run_id": "not-a-real-id", "iteration": 1},
        {"run_id": "20261125T070649-9e1fe6", "iteration": 1},
    ])

    result = load_runs(log)
    assert [run.run_id for run in result.runs] == ["20261125T070649-9e1fe6"]
    assert result.skipped_rows == 3


def test_counts_bad_lines(tmp_path):
    log = tmp_path / "exp.jsonl"
    log.write_text(
        '{"run_id": "20261125T070649-9e1fe6", "iteration": 1}\n'
        "not-json\n"
        '{"broken":\n',
        encoding="utf-8",
    )

    result = load_runs(log)
    assert result.total_lines == 3
    assert result.bad_lines == 2
    assert len(result.runs) == 1


def test_empty_file(tmp_path):
    log = tmp_path / "exp.jsonl"
    log.write_text("", encoding="utf-8")

    result = load_runs(log)
    assert result.runs == ()
    assert result.total_lines == 0
    assert result.bad_lines == 0
    assert result.skipped_rows == 0
