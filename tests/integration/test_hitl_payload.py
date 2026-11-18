"""统一审批结构契约测试（008-T004）。

对照 contracts/hitl-payload.md：三处 interrupt payload 均含
message（字符串）、params（dict）、scope ∈ {scapy_traffic, pktgen_traffic,
trex_script}；TRex payload 的 params.warning 含「静态扫描非硬边界」声明。
⚠️ 安全红线（R11）：全部流量工具 mock 覆盖整个调用生命周期，零真实流量。
"""

import json
from unittest.mock import MagicMock, patch

import pytest

ALLOWED_IP = "10.99.80.160"


def _capturing_interrupt(captured, answer):
    def fake_interrupt(payload):
        captured.append(payload)
        return answer
    return fake_interrupt


class TestScapyPayloadScope:
    @pytest.mark.parametrize("tool_name,message_frag", [
        ("traffic_send", "traffic send"),
        ("mixed_traffic_send", "mixed traffic send"),
    ])
    def test_scapy_payload_has_scope(self, tool_name, message_frag):
        from src.agent import tools as agent_tools

        tool = getattr(agent_tools, tool_name)
        captured = []

        if tool_name == "traffic_send":
            args = {"dst_ip": ALLOWED_IP, "dst_port": 8080}
            patch_target = "src.agent.tools.traffic_send_tool"
        else:
            args = {
                "dst_ip": ALLOWED_IP,
                "traffic_spec_json": json.dumps({
                    "streams": [
                        {"stream_id": "s1", "protocol_stack": ["IP", "UDP"],
                         "fields": {}, "percentage": 100},
                    ],
                }),
            }
            patch_target = "src.agent.tools.mixed_traffic_send_tool"

        with patch.object(agent_tools, "interrupt",
                          side_effect=_capturing_interrupt(captured, False)), \
             patch(patch_target):  # 拒绝 → 零流量；工具层仍 mock（R11）
            tool.invoke(args)

        payload = captured[0]
        assert isinstance(payload["message"], str)
        assert message_frag in payload["message"]
        assert isinstance(payload["params"], dict)
        assert payload["scope"] == "scapy_traffic"

    def test_mixed_payload_params_include_stream_summary(self):
        """mixed_traffic_send 的 params 含流量规格摘要（流数/协议构成）。"""
        from src.agent import tools as agent_tools

        captured = []
        spec = {
            "streams": [
                {"stream_id": "s1", "protocol_stack": ["IP", "UDP"],
                 "fields": {}, "percentage": 40},
                {"stream_id": "s2", "protocol_stack": ["IP", "TCP"],
                 "fields": {}, "percentage": 60},
            ],
        }
        with patch.object(agent_tools, "interrupt",
                          side_effect=_capturing_interrupt(captured, False)), \
             patch("src.agent.tools.mixed_traffic_send_tool"):
            agent_tools.mixed_traffic_send.invoke({
                "dst_ip": ALLOWED_IP,
                "traffic_spec_json": json.dumps(spec),
            })

        params = captured[0]["params"]
        assert params["stream_count"] == 2
        assert "protocols" in params
        assert "UDP" in str(params["protocols"]) and "TCP" in str(params["protocols"])


class TestPktgenPayloadScope:
    def test_pktgen_payload_has_scope_and_skill(self):
        from src.pktgen import adapter

        captured = []
        with patch.object(adapter, "is_dry_run", return_value=False), \
             patch.object(adapter, "interrupt",
                          side_effect=_capturing_interrupt(captured, False)), \
             patch.object(adapter, "_execute_skill"):  # R11：执行器 mock
            adapter.pktgen_udp_flood.invoke({
                "dst_ip": ALLOWED_IP, "rate": 50, "duration": 1000,
            })

        payload = captured[0]
        assert isinstance(payload["message"], str)
        assert "Pktgen" in payload["message"]
        assert isinstance(payload["params"], dict)
        assert payload["scope"] == "pktgen_traffic"
        assert "skill" in payload["params"]
        assert payload["params"]["skill"] == "udp_flood"
        assert payload["params"]["mode"] == "live"


class TestTrexPayloadScope:
    def test_trex_payload_has_scope_and_static_scan_warning(self, tmp_path, monkeypatch):
        from src.trex import tools as trex_tools

        monkeypatch.setattr(trex_tools, "get_trex_scripts_dir", lambda: tmp_path)
        monkeypatch.setattr(trex_tools, "is_trex_dry_run", lambda: False)
        (tmp_path / "s.py").write_text(
            f"target = '{ALLOWED_IP}'\n", encoding="utf-8",
        )

        captured = []
        with patch.object(trex_tools, "interrupt",
                          side_effect=_capturing_interrupt(captured, False)), \
             patch.object(trex_tools, "subprocess") as mock_sub:  # R11：执行 mock
            trex_tools.run_python_file.invoke({
                "filename": "s.py", "target_ip": ALLOWED_IP,
            })

        payload = captured[0]
        assert isinstance(payload["message"], str)
        assert payload["scope"] == "trex_script"
        params = payload["params"]
        assert isinstance(params, dict)
        assert params["filename"] == "s.py"
        warning = params["warning"]
        # 「静态扫描非硬边界」声明（FR-011）
        assert "尽力而为" in warning or "混淆" in warning
        assert "域名" in warning or "编码" in warning
