"""工具层 HITL 拒绝语义单测（008 契约）。

对 traffic_send / pktgen_udp_flood 工具层断言：当 interrupt() 返回 False（拒绝）时，
返回 ``{"success": false, "error": "HITL rejected by operator"}``。
"""

from unittest.mock import patch


def test_tool_layer_returns_hitl_rejected_on_false():
    """工具层：拒绝返回 {"success": false, "error": "HITL rejected by operator"}。"""
    from src.pktgen import adapter as pktgen_adapter
    from src.agent import tools as agent_tools

    # Scapy 工具层（traffic_send wrapper）
    with patch.object(agent_tools, "interrupt", return_value=False):
        result = agent_tools.traffic_send.invoke({
            "dst_ip": "10.99.80.160", "dst_port": 8080,
        })
    assert result["success"] is False
    assert "HITL rejected" in result["error"]

    # Pktgen 工具层
    with patch.object(pktgen_adapter, "is_dry_run", return_value=False), \
         patch.object(pktgen_adapter, "interrupt", return_value=False):
        result = pktgen_adapter.pktgen_udp_flood.invoke({
            "dst_ip": "10.99.80.160", "rate": 50, "duration": 1000,
        })
    assert result["success"] is False
    assert "HITL rejected" in result["error"]
