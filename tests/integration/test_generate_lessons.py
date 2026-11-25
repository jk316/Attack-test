"""End-to-end tests for scripts/generate_lessons.py (no LLM, hermetic)."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "generate_lessons.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("generate_lessons_mod", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_jsonl(path, rows):
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def _run(mod, monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["generate_lessons.py", *argv])
    mod.main()


def _base_args(log, lessons_dir, data_dir):
    return [
        "--log-path", str(log),
        "--lessons-dir", str(lessons_dir),
        "--data-dir", str(data_dir),
        "--no-llm",
    ]


def test_generate_and_idempotent(tmp_path, monkeypatch):
    mod = _load_script()
    log = tmp_path / "exp.jsonl"
    lessons_dir = tmp_path / "lessons"
    _write_jsonl(log, [
        {"run_id": "20261125T070649-9e1fe6", "iteration": 1,
         "tool": "traffic_send", "params": {"target_ip": "10.0.0.1"}, "rtt": 5.0},
        {"run_id": "20261124T012512-14e27c", "iteration": 1,
         "tool": "traffic_send", "params": {"target_ip": "10.0.0.2"}, "rtt": 3.0},
        {"run_id": "unknown", "iteration": 1},
    ])

    args = _base_args(log, lessons_dir, tmp_path)
    _run(mod, monkeypatch, args)

    f1 = lessons_dir / "20261125T070649-9e1fe6.md"
    f2 = lessons_dir / "20261124T012512-14e27c.md"
    assert f1.exists()
    assert f2.exists()
    assert not (lessons_dir / "unknown.md").exists()
    assert "## 经验教训" in f1.read_text(encoding="utf-8")

    content_before = f1.read_text(encoding="utf-8")
    _run(mod, monkeypatch, args)
    assert f1.read_text(encoding="utf-8") == content_before


def test_force_rewrites(tmp_path, monkeypatch):
    mod = _load_script()
    log = tmp_path / "exp.jsonl"
    lessons_dir = tmp_path / "lessons"
    _write_jsonl(log, [
        {"run_id": "20261125T070649-9e1fe6", "iteration": 1,
         "tool": "traffic_send", "params": {}, "rtt": 1.0},
    ])
    lessons_dir.mkdir()
    f = lessons_dir / "20261125T070649-9e1fe6.md"
    f.write_text("OLD", encoding="utf-8")

    args = _base_args(log, lessons_dir, tmp_path)
    _run(mod, monkeypatch, args)
    assert f.read_text(encoding="utf-8") == "OLD"

    _run(mod, monkeypatch, args + ["--force"])
    assert f.read_text(encoding="utf-8") != "OLD"


def test_list_only_prints(tmp_path, monkeypatch, capsys):
    mod = _load_script()
    log = tmp_path / "exp.jsonl"
    lessons_dir = tmp_path / "lessons"
    _write_jsonl(log, [
        {"run_id": "20261125T070649-9e1fe6", "iteration": 1},
        {"run_id": "20261124T012512-14e27c", "iteration": 1},
    ])

    _run(mod, monkeypatch, ["--log-path", str(log),
                            "--lessons-dir", str(lessons_dir), "--list"])
    out = capsys.readouterr().out

    assert "20261124T012512-14e27c" in out
    assert "20261125T070649-9e1fe6" in out
    assert not (lessons_dir / "20261125T070649-9e1fe6.md").exists()


def test_latest_only_newest(tmp_path, monkeypatch):
    mod = _load_script()
    log = tmp_path / "exp.jsonl"
    lessons_dir = tmp_path / "lessons"
    _write_jsonl(log, [
        {"run_id": "20261124T012512-14e27c", "iteration": 1},
        {"run_id": "20261125T070649-9e1fe6", "iteration": 1},
    ])

    _run(mod, monkeypatch, _base_args(log, lessons_dir, tmp_path) + ["--latest"])

    assert (lessons_dir / "20261125T070649-9e1fe6.md").exists()
    assert not (lessons_dir / "20261124T012512-14e27c.md").exists()


def test_run_id_filters(tmp_path, monkeypatch):
    mod = _load_script()
    log = tmp_path / "exp.jsonl"
    lessons_dir = tmp_path / "lessons"
    _write_jsonl(log, [
        {"run_id": "20261124T012512-14e27c", "iteration": 1},
        {"run_id": "20261125T070649-9e1fe6", "iteration": 1},
    ])

    _run(mod, monkeypatch, _base_args(log, lessons_dir, tmp_path)
         + ["--run-id", "20261124T012512-14e27c"])

    assert (lessons_dir / "20261124T012512-14e27c.md").exists()
    assert not (lessons_dir / "20261125T070649-9e1fe6.md").exists()


def test_missing_log_exits_nonzero(tmp_path, monkeypatch):
    mod = _load_script()
    with pytest.raises(SystemExit) as excinfo:
        _run(mod, monkeypatch, ["--log-path", str(tmp_path / "nope.jsonl")])
    assert excinfo.value.code != 0
