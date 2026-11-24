"""Unit tests for the generic file tools (read_file / grep / write_file).

All I/O goes through tmp_path; config getters are monkeypatched so no real
server paths or project files are touched.
"""
import pytest

from src.tools.file_tools import (
    MAX_READ_CHARS,
    MAX_WRITE_CHARS,
    _resolve_under_root,
    read_file,
    grep,
    write_file,
)


# ── _resolve_under_root ─────────────────────────────────────────────

class TestResolveUnderRoot:
    def test_relative_path(self, tmp_path):
        assert _resolve_under_root("sub/f.py", tmp_path) == (tmp_path / "sub" / "f.py").resolve()

    def test_rejects_traversal(self, tmp_path):
        with pytest.raises(ValueError):
            _resolve_under_root("../evil.py", tmp_path)

    def test_rejects_absolute_escape(self, tmp_path):
        with pytest.raises(ValueError):
            _resolve_under_root("/etc/passwd", tmp_path)

    def test_rejects_empty(self, tmp_path):
        with pytest.raises(ValueError):
            _resolve_under_root("", tmp_path)


# ── read_file ───────────────────────────────────────────────────────

class TestReadFile:
    def _root(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.tools.file_tools.get_trex_lib_dir", lambda: str(tmp_path))
        return tmp_path

    def test_root_unset(self, monkeypatch):
        monkeypatch.setattr("src.tools.file_tools.get_trex_lib_dir", lambda: "")
        r = read_file.invoke({"path": "a.py"})
        assert r["success"] is False
        assert "not set" in r["error"]

    def test_reads_relative(self, tmp_path, monkeypatch):
        self._root(tmp_path, monkeypatch)
        (tmp_path / "trex" / "stl").mkdir(parents=True)
        (tmp_path / "trex" / "stl" / "c.py").write_text("x = 1\n")
        r = read_file.invoke({"path": "trex/stl/c.py"})
        assert r["success"] is True
        assert "x = 1" in r["content"]
        assert r["truncated"] is False

    def test_rejects_traversal(self, tmp_path, monkeypatch):
        self._root(tmp_path, monkeypatch)
        r = read_file.invoke({"path": "../secret.txt"})
        assert r["success"] is False
        assert "escapes" in r["error"]

    def test_rejects_absolute_escape(self, tmp_path, monkeypatch):
        self._root(tmp_path, monkeypatch)
        r = read_file.invoke({"path": "/etc/passwd"})
        assert r["success"] is False
        assert "escapes" in r["error"]

    def test_not_a_file(self, tmp_path, monkeypatch):
        self._root(tmp_path, monkeypatch)
        r = read_file.invoke({"path": "."})
        assert r["success"] is False
        assert "not a file" in r["error"]

    def test_truncates_large(self, tmp_path, monkeypatch):
        self._root(tmp_path, monkeypatch)
        (tmp_path / "big.py").write_text("x" * (MAX_READ_CHARS + 10))
        r = read_file.invoke({"path": "big.py"})
        assert r["success"] is True
        assert r["truncated"] is True
        assert "… (+10 chars)" in r["content"]


# ── grep ────────────────────────────────────────────────────────────

class TestGrep:
    def _root(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.tools.file_tools.get_trex_lib_dir", lambda: str(tmp_path))
        (tmp_path / "a.py").write_text("def add_streams(self):\n    pass\n")
        (tmp_path / "b.py").write_text("def connect(self):\n    pass\n")
        return tmp_path

    def test_finds_matches(self, tmp_path, monkeypatch):
        self._root(tmp_path, monkeypatch)
        r = grep.invoke({"pattern": "add_streams"})
        assert r["success"] is True
        assert r["match_count"] == 1
        assert r["matches"][0]["file"] == "a.py"
        assert r["matches"][0]["line"] == 1
        assert "add_streams" in r["matches"][0]["text"]

    def test_no_match(self, tmp_path, monkeypatch):
        self._root(tmp_path, monkeypatch)
        r = grep.invoke({"pattern": "zzz_nope"})
        assert r["success"] is True
        assert r["matches"] == []

    def test_invalid_regex(self, tmp_path, monkeypatch):
        self._root(tmp_path, monkeypatch)
        r = grep.invoke({"pattern": "("})
        assert r["success"] is False
        assert "invalid regex" in r["error"]

    def test_rejects_traversal(self, tmp_path, monkeypatch):
        self._root(tmp_path, monkeypatch)
        r = grep.invoke({"pattern": "x", "path": "../"})
        assert r["success"] is False
        assert "escapes" in r["error"]

    def test_root_unset(self, monkeypatch):
        monkeypatch.setattr("src.tools.file_tools.get_trex_lib_dir", lambda: "")
        r = grep.invoke({"pattern": "x"})
        assert r["success"] is False
        assert "not set" in r["error"]


# ── write_file ──────────────────────────────────────────────────────

class TestWriteFile:
    def test_writes_into_scratch(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.tools.file_tools.get_scratch_dir", lambda: tmp_path)
        r = write_file.invoke({"path": "notes/x.md", "content": "# hi\n"})
        assert r["success"] is True
        assert (tmp_path / "notes" / "x.md").read_text() == "# hi\n"

    def test_rejects_traversal(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.tools.file_tools.get_scratch_dir", lambda: tmp_path)
        r = write_file.invoke({"path": "../evil.py", "content": "x"})
        assert r["success"] is False
        assert "escapes" in r["error"]

    def test_rejects_oversized(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.tools.file_tools.get_scratch_dir", lambda: tmp_path)
        r = write_file.invoke({"path": "big.txt", "content": "x" * (MAX_WRITE_CHARS + 1)})
        assert r["success"] is False
        assert "chars" in r["error"]
