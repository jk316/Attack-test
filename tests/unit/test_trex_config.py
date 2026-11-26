"""Unit tests for TRex L2 getters (dst/src MAC, start_force)."""
import pytest

from src.trex import config as trex_config


def _patch_section(monkeypatch, section):
    monkeypatch.setattr(trex_config, "_load_trex_section", lambda: section)


class TestL2Getters:
    def test_dst_mac_env_wins(self, monkeypatch):
        _patch_section(monkeypatch, {"dst_mac": "aa:bb:cc:dd:ee:ff"})
        monkeypatch.setenv("TREX_DST_MAC", "ff:ff:ff:ff:ff:ff")
        assert trex_config.get_trex_dst_mac() == "ff:ff:ff:ff:ff:ff"

    def test_dst_mac_topology_fallback(self, monkeypatch):
        monkeypatch.delenv("TREX_DST_MAC", raising=False)
        _patch_section(monkeypatch, {"dst_mac": "aa:bb:cc:dd:ee:ff"})
        assert trex_config.get_trex_dst_mac() == "aa:bb:cc:dd:ee:ff"

    def test_dst_mac_default(self, monkeypatch):
        monkeypatch.delenv("TREX_DST_MAC", raising=False)
        _patch_section(monkeypatch, {})
        assert trex_config.get_trex_dst_mac() == "f0:c4:78:4c:a5:55"

    def test_src_mac_env_and_default(self, monkeypatch):
        monkeypatch.delenv("TREX_SRC_MAC", raising=False)
        _patch_section(monkeypatch, {})
        assert trex_config.get_trex_src_mac() == "58:a2:e1:6d:89:2c"
        monkeypatch.setenv("TREX_SRC_MAC", "00:11:22:33:44:55")
        assert trex_config.get_trex_src_mac() == "00:11:22:33:44:55"

    def test_start_force_default_true(self, monkeypatch):
        monkeypatch.delenv("TREX_START_FORCE", raising=False)
        _patch_section(monkeypatch, {})
        assert trex_config.get_trex_start_force() is True

    @pytest.mark.parametrize("value", ["false", "0", "no", "FALSE", ""])
    def test_start_force_falsy_values(self, monkeypatch, value):
        monkeypatch.setenv("TREX_START_FORCE", value)
        assert trex_config.get_trex_start_force() is False

    def test_start_force_from_topology(self, monkeypatch):
        monkeypatch.delenv("TREX_START_FORCE", raising=False)
        _patch_section(monkeypatch, {"start_force": False})
        assert trex_config.get_trex_start_force() is False


class TestLibDir:
    def test_env_wins(self, monkeypatch):
        _patch_section(monkeypatch, {"lib_dir": "/topo"})
        monkeypatch.setenv("TREX_LIB_DIR", "/env")
        assert trex_config.get_trex_lib_dir() == "/env"

    def test_topology_fallback(self, monkeypatch):
        monkeypatch.delenv("TREX_LIB_DIR", raising=False)
        _patch_section(monkeypatch, {"lib_dir": "/topo"})
        assert trex_config.get_trex_lib_dir() == "/topo"

    def test_unset_is_empty(self, monkeypatch):
        monkeypatch.delenv("TREX_LIB_DIR", raising=False)
        _patch_section(monkeypatch, {})
        assert trex_config.get_trex_lib_dir() == ""
