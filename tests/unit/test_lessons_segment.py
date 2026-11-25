"""Tests for src/lessons/segment.py — agent-log run-segment extraction."""

from src.lessons.segment import extract_run_segment, find_run_segment

RUN_ID = "20261125T070649-9e1fe6"


def test_extract_segment():
    text = (
        "preamble\n"
        f"[RUN START] {RUN_ID}\n"
        "hello world\n"
        f"[RUN END] {RUN_ID}\n"
        "after\n"
    )
    assert extract_run_segment(RUN_ID, text) == "hello world"


def test_extract_missing_start_returns_none():
    assert extract_run_segment(RUN_ID, "no markers here\n") is None


def test_extract_unpaired_start_returns_none():
    text = f"[RUN START] {RUN_ID}\nhello\n"
    assert extract_run_segment(RUN_ID, text) is None


def test_extract_does_not_span_another_run():
    text = (
        f"[RUN START] {RUN_ID}\n"
        "mine\n"
        "[RUN START] 20261125T080000-abcdef\n"
        "other\n"
        f"[RUN END] 20261125T080000-abcdef\n"
    )
    assert extract_run_segment(RUN_ID, text) is None


def test_find_run_segment(tmp_path):
    (tmp_path / "agent-2026-11-25.log").write_text(
        f"[RUN START] {RUN_ID}\nsegment content\n[RUN END] {RUN_ID}\n",
        encoding="utf-8",
    )
    assert find_run_segment(RUN_ID, tmp_path) == "segment content"


def test_find_run_segment_missing_file(tmp_path):
    assert find_run_segment(RUN_ID, tmp_path) is None
