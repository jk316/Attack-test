"""Integration test: main() writes paired [RUN START]/[RUN END] markers."""

import sys


class _StubGraph:
    def invoke(self, *args, **kwargs):
        return None

    def get_state(self, *args, **kwargs):
        return None


def test_main_writes_paired_run_markers(tmp_path, monkeypatch):
    import src.main as main_mod

    log_path = tmp_path / "agent-test.log"
    monkeypatch.setattr(main_mod, "_agent_log_path", lambda: str(log_path))
    monkeypatch.setattr(main_mod, "build_graph", lambda **kw: _StubGraph())
    monkeypatch.setattr(
        main_mod, "start_experiment_monitors",
        lambda ip, http=None: {"ping": True, "http": False},
    )
    monkeypatch.setattr(main_mod, "stop_experiment_monitors", lambda: None)
    monkeypatch.setattr(
        sys, "argv", ["main.py", "--max-iters", "1", "--auto-approve"],
    )

    main_mod.main()

    content = log_path.read_text(encoding="utf-8")
    start_lines = [l for l in content.splitlines() if "[RUN START]" in l]
    end_lines = [l for l in content.splitlines() if "[RUN END]" in l]

    assert len(start_lines) == 1
    assert len(end_lines) == 1
    assert start_lines[0].split("] ", 1)[1] == end_lines[0].split("] ", 1)[1]
