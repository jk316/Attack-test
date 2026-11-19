"""mixed_traffic 源地址伪造拒绝测试（008-T010）。

FR-004：流量规格（JSON spec）内不得存在可伪造 src_ip 的路径——
合法 spec 通过；含 IP.src 自定义的 spec 被拒绝并返回明确错误。
"""

import json

import pytest

from src.tools.mixed_traffic_tool import validate_traffic_spec


def _spec(fields_ip=None, **stream_overrides):
    stream = {
        "stream_id": "s1",
        "protocol_stack": ["IP", "UDP"],
        "fields": {},
        "percentage": 100,
    }
    stream.update(stream_overrides)
    if fields_ip is not None:
        stream["fields"] = {"IP": fields_ip}
    return {"streams": [stream]}


class TestMixedSrcIpForbidden:
    def test_legal_spec_passes(self):
        streams = validate_traffic_spec(_spec())
        assert len(streams) == 1

    def test_ip_src_field_rejected(self):
        with pytest.raises(ValueError, match="IP.src 不允许自定义"):
            validate_traffic_spec(_spec(fields_ip={"src": "1.2.3.4"}))

    def test_ip_src_case_insensitive_rejected(self):
        with pytest.raises(ValueError, match="IP.src 不允许自定义"):
            validate_traffic_spec(_spec(fields_ip={"Src": "1.2.3.4"}))

    def test_ip_dst_field_allowed_but_overwritten(self):
        """IP.dst 由工具强制覆盖为目标，spec 内 dst 不拒绝（伪造源才拒绝）。"""
        streams = validate_traffic_spec(_spec(fields_ip={"dst": "8.8.8.8"}))
        assert len(streams) == 1

    def test_other_protocol_src_like_fields_unaffected(self):
        """仅 IP 层 src 禁止；TCP/UDP 的 sport 等字段不受影响。"""
        spec = {
            "streams": [{
                "stream_id": "s1",
                "protocol_stack": ["IP", "TCP"],
                "fields": {"TCP": {"sport": 1234}},
                "percentage": 100,
            }],
        }
        streams = validate_traffic_spec(spec)
        assert len(streams) == 1


class TestMixedEndToEndSrcIpRejected:
    def test_mixed_traffic_send_rejects_src_ip_spec(self):
        """工具整体路径：含伪造源 spec 的调用被拒绝（校验先于任何发送）。"""
        from unittest.mock import patch

        from src.agent import tools as agent_tools

        spec = {
            "streams": [{
                "stream_id": "s1",
                "protocol_stack": ["IP", "UDP"],
                "fields": {"IP": {"src": "1.2.3.4"}},
                "percentage": 100,
            }],
        }
        # 审批放行后，规格校验在任何发包前拒绝（R11：无真实流量）
        with patch.object(agent_tools, "interrupt", return_value=True):
            with pytest.raises(ValueError, match="IP.src 不允许自定义"):
                agent_tools.mixed_traffic_send.invoke({
                    "dst_ip": "10.99.80.160",
                    "traffic_spec_json": json.dumps(spec),
                })
