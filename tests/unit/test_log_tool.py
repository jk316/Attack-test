"""Tests for log_tool - RED stage"""
import json
import os
import tempfile
import pytest
from pathlib import Path


class TestLogTool:
    """Test suite for log_tool"""

    def test_writes_jsonl_line_to_file(self):
        """应写入一行 JSONL 到文件"""
        from src.tools.log_tool import log_tool

        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            log_path = f.name

        try:
            entry = {
                "params": {"pps": 100, "duration_s": 5},
                "rtt": 1.234,
                "loss": 0.0
            }
            result = log_tool(log_path, entry)

            assert result["success"] is True

            with open(log_path, "r") as f:
                lines = f.readlines()
            assert len(lines) == 1

            parsed = json.loads(lines[0])
            assert "timestamp" in parsed
            assert parsed["params"] == entry["params"]
            assert parsed["rtt"] == 1.234
            assert parsed["loss"] == 0.0
        finally:
            os.unlink(log_path)

    def test_append_mode_preserves_existing_lines(self):
        """追加模式应保留已有行并追加新行"""
        from src.tools.log_tool import log_tool

        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            log_path = f.name
            # 写入一行预存在数据
            f.write(json.dumps({"existing": "data"}) + "\n")

        try:
            entry = {"params": {}, "rtt": 2.0, "loss": 50.0}
            log_tool(log_path, entry)

            with open(log_path, "r") as f:
                lines = f.readlines()

            assert len(lines) == 2
            assert json.loads(lines[0]) == {"existing": "data"}
            parsed_new = json.loads(lines[1])
            assert parsed_new["rtt"] == 2.0
            assert parsed_new["loss"] == 50.0
        finally:
            os.unlink(log_path)

    def test_fields_completeness(self):
        """写入的记录应包含 timestamp, params, rtt, loss 字段"""
        from src.tools.log_tool import log_tool

        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            log_path = f.name

        try:
            entry = {
                "params": {"pps": 50, "flow_count": 3},
                "rtt": 3.5,
                "loss": 10.0
            }
            log_tool(log_path, entry)

            with open(log_path, "r") as f:
                parsed = json.loads(f.readline())

            required = ["timestamp", "params", "rtt", "loss"]
            for field in required:
                assert field in parsed, f"Missing required field: {field}"
            assert isinstance(parsed["timestamp"], str)
        finally:
            os.unlink(log_path)

    def test_timestamp_is_iso8601(self):
        """timestamp 应为 ISO 8601 格式"""
        from src.tools.log_tool import log_tool

        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            log_path = f.name

        try:
            log_tool(log_path, {"params": {}, "rtt": 0, "loss": 0})

            with open(log_path, "r") as f:
                parsed = json.loads(f.readline())

            ts = parsed["timestamp"]
            # ISO 8601 格式应包含 T 和时区或+00:00，或至少包含 T
            assert "T" in ts
        finally:
            os.unlink(log_path)

    def test_creates_file_if_not_exists(self):
        """文件不存在时应自动创建"""
        from src.tools.log_tool import log_tool

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "new_log.jsonl")
            assert not os.path.exists(log_path)

            log_tool(log_path, {"params": {}, "rtt": 0, "loss": 0})

            assert os.path.exists(log_path)
            with open(log_path, "r") as f:
                lines = f.readlines()
            assert len(lines) == 1

    def test_handles_nonexistent_directory(self):
        """目录不存在时应返回错误"""
        from src.tools.log_tool import log_tool

        log_path = "/nonexistent_dir_12345/log.jsonl"
        result = log_tool(log_path, {"params": {}, "rtt": 0, "loss": 0})

        assert result["success"] is False
        assert "error" in result

    def test_output_includes_iteration_if_provided(self):
        """如果 entry 包含 iteration，应写入"""
        from src.tools.log_tool import log_tool

        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            log_path = f.name

        try:
            entry = {
                "params": {"pps": 10},
                "rtt": 1.0,
                "loss": 0.0,
                "iteration": 5
            }
            log_tool(log_path, entry)

            with open(log_path, "r") as f:
                parsed = json.loads(f.readline())

            assert parsed["iteration"] == 5
        finally:
            os.unlink(log_path)

    def test_roundtrip_multiple_entries(self):
        """多次写入应正确追加多行"""
        from src.tools.log_tool import log_tool

        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            log_path = f.name

        try:
            for i in range(5):
                entry = {
                    "params": {"pps": i * 10},
                    "rtt": float(i),
                    "loss": float(i * 5),
                    "iteration": i
                }
                log_tool(log_path, entry)

            with open(log_path, "r") as f:
                lines = f.readlines()

            assert len(lines) == 5
            for i, line in enumerate(lines):
                parsed = json.loads(line)
                assert parsed["iteration"] == i
                assert parsed["rtt"] == float(i)
        finally:
            os.unlink(log_path)

    def test_write_error_returns_failure(self):
        """写入错误时应返回 success=False"""
        from src.tools.log_tool import log_tool
        from unittest.mock import patch

        with patch("builtins.open", side_effect=IOError("disk full")):
            result = log_tool("/tmp/test.jsonl", {"params": {}, "rtt": 0, "loss": 0})

        assert result["success"] is False
        assert "error" in result
