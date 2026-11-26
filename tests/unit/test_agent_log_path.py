"""Unit tests for the daily-rotated agent log path (spec: 按天分文件)."""

import re

from src.main import _agent_log_path


def test_daily_rotated_path():
    path = _agent_log_path()
    assert re.fullmatch(r"data/agent-\d{4}-\d{2}-\d{2}\.log", path), path
