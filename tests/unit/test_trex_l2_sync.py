"""Sync tests: keep the multiple TRex L2 default copies and env injection
paths from drifting apart (review fix I2).

The shipped experiment.json/topology.yaml are intentionally NOT compared
against code literals here — customizing those files is the documented
config surface and must not fail CI. The invariant that matters is:
(a) the two code copies (src/trex/config.py, trex_scripts/trex_common.py)
    stay identical, and
(b) both entry points inject the config into env so prompt and executed
    scripts read the same values.
"""
import importlib
import sys
from pathlib import Path

import pytest

from src.trex import config as trex_config

SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "trex_scripts"


def _fresh_trex_common(monkeypatch):
    for key in ("TREX_DST_MAC", "TREX_SRC_MAC", "TREX_START_FORCE", "TREX_HOST"):
        monkeypatch.delenv(key, raising=False)
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    mod = importlib.import_module("trex_common")
    importlib.reload(mod)
    return mod


class TestCodeCopySync:
    def test_config_defaults_match_trex_common(self, monkeypatch):
        mod = _fresh_trex_common(monkeypatch)
        assert mod.DST_MAC == trex_config._DEFAULT_DST_MAC
        assert mod.SRC_MAC == trex_config._DEFAULT_SRC_MAC
        assert mod.TREX_SERVER == trex_config._DEFAULT_HOST
        assert mod.START_FORCE is True


class TestBackendTrexEnv:
    def test_apply_trex_env_sets_all(self, monkeypatch):
        import os

        from backend.experiment import _apply_trex_env

        for k in ("TREX_HOST", "TREX_DST_MAC", "TREX_SRC_MAC", "TREX_START_FORCE"):
            monkeypatch.delenv(k, raising=False)
        _apply_trex_env({"host": "10.99.80.222",
                         "dst_mac": "aa:bb:cc:dd:ee:ff",
                         "src_mac": "11:22:33:44:55:66",
                         "start_force": False})
        assert os.environ["TREX_HOST"] == "10.99.80.222"
        assert os.environ["TREX_DST_MAC"] == "aa:bb:cc:dd:ee:ff"
        assert os.environ["TREX_SRC_MAC"] == "11:22:33:44:55:66"
        assert os.environ["TREX_START_FORCE"] == "False"

    def test_apply_trex_env_missing_keys_noop(self, monkeypatch):
        import os

        from backend.experiment import _apply_trex_env

        for k in ("TREX_HOST", "TREX_DST_MAC", "TREX_SRC_MAC", "TREX_START_FORCE"):
            monkeypatch.delenv(k, raising=False)
        _apply_trex_env({})
        for k in ("TREX_HOST", "TREX_DST_MAC", "TREX_SRC_MAC", "TREX_START_FORCE"):
            assert k not in os.environ
