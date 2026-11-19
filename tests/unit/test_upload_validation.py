"""PCAP 上传校验测试（007-T012）。

对照 contracts/rest-api.md POST /api/upload/pcap：扩展名白名单
.pcap/.pcapng/.cap（大小写不敏感）、>100MB 拒绝（413）、空文件名拒绝（400）、
成功时 file_path 形如 data/uploads/<8位前缀>_<原名>、校验失败不落盘。
当前服务端无校验——先确认现状失败（RED）。
"""

import io

import httpx
import pytest

from backend import server as server_mod

TRANSPORT = httpx.ASGITransport(app=server_mod.app)


@pytest.fixture(autouse=True)
def _isolate_upload_dir(tmp_path, monkeypatch):
    """上传目录指向 tmp，绝不污染仓库 data/uploads/。"""
    monkeypatch.setattr(server_mod, "_DATA_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def client():
    async def _request(**kwargs):
        async with httpx.AsyncClient(transport=TRANSPORT,
                                     base_url="http://test") as c:
            return await c.post("/api/upload/pcap", **kwargs)
    return _request


def _upload(client, filename, content=b"fake-pcap-bytes"):
    return client(files={"file": (filename, io.BytesIO(content))})


class TestUploadExtensionWhitelist:
    @pytest.mark.asyncio
    async def test_pcap_extension_accepted(self, client, tmp_path):
        resp = await _upload(client, "sample.pcap")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["file_name"] == "sample.pcap"
        assert body["file_path"].startswith("data/uploads/")
        assert body["file_path"].endswith("_sample.pcap")
        # <8位前缀>_<原名>
        prefix = body["file_path"].split("/")[-1].split("_", 1)[0]
        assert len(prefix) == 8
        assert body["size_bytes"] == len(b"fake-pcap-bytes")

    @pytest.mark.asyncio
    async def test_pcapng_and_cap_accepted(self, client):
        for name in ("sample.pcapng", "sample.cap"):
            resp = await _upload(client, name)
            assert resp.status_code == 200, name
            assert resp.json()["success"] is True

    @pytest.mark.asyncio
    async def test_extension_case_insensitive(self, client):
        resp = await _upload(client, "SAMPLE.PCAP")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    @pytest.mark.asyncio
    async def test_disallowed_extension_rejected(self, client, tmp_path):
        resp = await _upload(client, "evil.txt")
        assert resp.status_code == 400
        body = resp.json()
        assert body["success"] is False
        assert "不支持的文件类型" in body["error"]
        assert list(tmp_path.iterdir()) == []  # 校验失败不落盘

    @pytest.mark.asyncio
    async def test_empty_filename_rejected(self):
        """空文件名 → 400「未选择文件」。

        注：框架层（Starlette）会把「缺 filename 的 multipart 部件」以 422 拦截；
        本用例直接驱动处理器验证 400 分支（契约口径）。
        """
        from backend.server import api_upload_pcap

        class FakeUpload:
            filename = ""

        resp = await api_upload_pcap(FakeUpload())
        assert resp.status_code == 400
        import json as _json
        body = _json.loads(resp.body.decode("utf-8"))
        assert "未选择文件" in body["error"]


class TestUploadSizeLimit:
    @pytest.mark.asyncio
    async def test_constant_is_100mb(self):
        assert server_mod.MAX_UPLOAD_BYTES == 100 * 1024 * 1024

    @pytest.mark.asyncio
    async def test_over_limit_rejected_413(self, client, tmp_path, monkeypatch):
        # 用小上限模拟：超限 → 413 且不落盘（避免真实 100MB 上传）
        monkeypatch.setattr(server_mod, "MAX_UPLOAD_BYTES", 1024)
        resp = await _upload(client, "big.pcap", content=b"x" * 2048)
        assert resp.status_code == 413
        body = resp.json()
        assert body["success"] is False
        assert "大小上限" in body["error"]
        assert list(tmp_path.iterdir()) == []  # 校验失败不落盘

    @pytest.mark.asyncio
    async def test_within_limit_accepted(self, client, monkeypatch):
        monkeypatch.setattr(server_mod, "MAX_UPLOAD_BYTES", 1024)
        resp = await _upload(client, "small.pcap", content=b"x" * 512)
        assert resp.status_code == 200
        assert resp.json()["success"] is True
