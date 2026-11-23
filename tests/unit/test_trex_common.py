"""Unit tests for trex_scripts/trex_common.py.

Importing the module in this (trex-less) environment is itself the first test:
top level must not import trex_stl_lib / trex_astf_lib.
"""
import importlib
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "trex_scripts"


def _fresh_module(monkeypatch):
    for key in ("TREX_DST_MAC", "TREX_SRC_MAC", "TREX_START_FORCE", "TREX_HOST"):
        monkeypatch.delenv(key, raising=False)
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    mod = importlib.import_module("trex_common")
    importlib.reload(mod)
    return mod


@pytest.fixture()
def trex_common(monkeypatch):
    return _fresh_module(monkeypatch)


class TestConstants:
    def test_module_imports_without_trex_libs(self, trex_common):
        assert trex_common.DST_MAC == "f4:e9:75:ee:51:69"
        assert trex_common.SRC_MAC == "58:a2:e1:6d:89:2c"
        assert trex_common.TREX_SERVER == "127.0.0.1"  # 与 config._DEFAULT_HOST 对齐
        assert trex_common.START_FORCE is True

    def test_env_overrides(self, monkeypatch):
        # 注意：先设 env 再 reload（不能用 _fresh_module，它会先清 env）。
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        monkeypatch.setenv("TREX_DST_MAC", "aa:bb:cc:dd:ee:ff")
        monkeypatch.setenv("TREX_SRC_MAC", "11:22:33:44:55:66")
        monkeypatch.setenv("TREX_START_FORCE", "false")
        mod = importlib.import_module("trex_common")
        importlib.reload(mod)
        assert mod.DST_MAC == "aa:bb:cc:dd:ee:ff"
        assert mod.SRC_MAC == "11:22:33:44:55:66"
        assert mod.START_FORCE is False


class _FakeClient:
    def __init__(self):
        self.start_kwargs = None

    def start(self, **kwargs):
        self.start_kwargs = kwargs


class TestStartSafe:
    def test_start_safe_passes_force_true(self, trex_common):
        client = _FakeClient()
        trex_common.start_safe(client, ports=[0], mult="50%", duration=5)
        assert client.start_kwargs == {
            "ports": [0], "mult": "50%", "duration": 5, "force": True,
        }

    def test_start_safe_defaults(self, trex_common):
        client = _FakeClient()
        trex_common.start_safe(client)
        assert client.start_kwargs["force"] is True
        assert client.start_kwargs["ports"] == [0]
        assert client.start_kwargs["mult"] == "100%"
        assert client.start_kwargs["duration"] == 10

    def test_start_safe_respects_start_force_env(self, monkeypatch):
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        monkeypatch.setenv("TREX_START_FORCE", "false")
        mod = importlib.import_module("trex_common")
        importlib.reload(mod)
        client = _FakeClient()
        mod.start_safe(client)
        assert client.start_kwargs["force"] is False

    def test_start_safe_explicit_force_overrides_env(self, monkeypatch):
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        monkeypatch.setenv("TREX_START_FORCE", "false")
        mod = importlib.import_module("trex_common")
        importlib.reload(mod)
        client = _FakeClient()
        mod.start_safe(client, force=True)
        assert client.start_kwargs["force"] is True


class TestMakeClient:
    def test_make_client_connects_with_server(self, trex_common, monkeypatch):
        class FakeSTLClient:
            def __init__(self, server):
                self.server = server
                self.connected = False

            def connect(self):
                self.connected = True

        monkeypatch.setitem(sys.modules, "trex_stl_lib.api",
                            type("fake_api", (), {"STLClient": FakeSTLClient})())
        client = trex_common.make_client(server="10.99.80.222")
        assert client.server == "10.99.80.222"
        assert client.connected is True
