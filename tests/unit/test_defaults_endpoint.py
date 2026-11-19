"""默认值接口测试（007-T013）。

对照 contracts/rest-api.md GET /api/experiment/defaults：返回 experiment.json
的 target_ip/max_iters/no_improve_limit；配置修改后（临时写读）重启进程读取
生效；POST /api/experiment/start 对 max_iters/no_improve_limit ≥1 校验。
当前接口尚不存在——先确认现状失败（RED）。
"""

import json
from pathlib import Path

import httpx
import pytest

from backend import server as server_mod

TRANSPORT = httpx.ASGITransport(app=server_mod.app)

_REAL_CONFIG = Path(__file__).resolve().parent.parent.parent / "src" / "config" / "experiment.json"


@pytest.fixture
def client():
    async def _req(method, path, **kwargs):
        async with httpx.AsyncClient(transport=TRANSPORT,
                                     base_url="http://test") as c:
            return await c.request(method, path, **kwargs)
    return _req


class TestDefaultsEndpoint:
    @pytest.mark.asyncio
    async def test_returns_experiment_json_defaults(self, client):
        resp = await client("GET", "/api/experiment/defaults")
        assert resp.status_code == 200
        body = resp.json()
        with open(_REAL_CONFIG, encoding="utf-8") as f:
            cfg = json.load(f)
        assert body["target_ip"] == cfg["target_ip"]
        assert body["max_iters"] == cfg["max_iters"]
        assert body["no_improve_limit"] == cfg["no_improve_limit"]

    @pytest.mark.asyncio
    async def test_missing_keys_fall_back_to_builtin(self, client, monkeypatch):
        monkeypatch.setattr(server_mod, "_DEFAULTS", {})
        resp = await client("GET", "/api/experiment/defaults")
        assert resp.status_code == 200
        body = resp.json()
        assert body["max_iters"] >= 1
        assert body["no_improve_limit"] >= 1
        assert isinstance(body["target_ip"], str)

    def test_loader_reads_modified_config(self, tmp_path, monkeypatch):
        """配置修改后新进程（重新加载）读取生效——loader 直读文件。"""
        cfg_file = tmp_path / "experiment.json"
        cfg_file.write_text(json.dumps({
            "target_ip": "100.1.11.3", "max_iters": 7, "no_improve_limit": 3,
        }), encoding="utf-8")
        monkeypatch.setattr(server_mod, "_EXPERIMENT_CONFIG_PATH", cfg_file)
        loaded = server_mod._load_defaults()
        assert loaded["target_ip"] == "100.1.11.3"
        assert loaded["max_iters"] == 7
        assert loaded["no_improve_limit"] == 3

    def test_loader_missing_file_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(server_mod, "_EXPERIMENT_CONFIG_PATH",
                            tmp_path / "nope.json")
        assert server_mod._load_defaults() == {}


class TestStartRequestValidation:
    @pytest.mark.asyncio
    async def test_max_iters_below_one_rejected(self, client):
        resp = await client("POST", "/api/experiment/start",
                            json={"target_ip": "10.99.80.160", "max_iters": 0})
        assert resp.status_code == 400
        body = resp.json()
        assert body["success"] is False
        assert "max_iters" in body["error"]

    @pytest.mark.asyncio
    async def test_no_improve_limit_below_one_rejected(self, client):
        resp = await client("POST", "/api/experiment/start",
                            json={"no_improve_limit": -1})
        assert resp.status_code == 400
        assert "no_improve_limit" in resp.json()["error"]

    @pytest.mark.asyncio
    async def test_valid_request_echoes_with_defaults(self, client):
        resp = await client("POST", "/api/experiment/start",
                            json={"target_ip": "10.99.80.160"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["params"]["max_iters"] >= 1
        assert body["params"]["no_improve_limit"] >= 1
