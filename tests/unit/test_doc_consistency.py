"""文档一致性测试（008-T018，SC-008）。

解析 src/agent/tools.py 的 @tool docstring 中上限数字、
src/tools/traffic_send_tool.py 常量、src/prompts/system_prompt.j2 上限表
三处，断言 0 冲突（自动化守住「文档真实性」）。
"""

import re

import importlib

_TST = importlib.import_module("src.tools.traffic_send_tool")
_MTT = importlib.import_module("src.tools.mixed_traffic_tool")

DOC_PATTERNS = {
    "traffic_send": [
        (r"duration in seconds \(max (\d+)\)", "MAX_DURATION_S"),
        (r"Packets per second \(max (\d+)\)", "MAX_PPS"),
        (r"Payload size in bytes \(max (\d+)\)", "MAX_PACKET_SIZE"),
        (r"unique sport \(max (\d+)\)", "MAX_FLOW_COUNT"),
        (r"inter-packet interval in ms \(max (\d+)\)", "MAX_IAT_JITTER_MS"),
    ],
    "mixed_traffic_send": [
        (r"duration in seconds \(max (\d+)\)", "MAX_DURATION_S"),
        (r"across all streams \(max (\d+)\)", "MAX_PPS"),
    ],
}


def _tool_description(tool_name):
    from src.agent import tools as agent_tools
    return getattr(agent_tools, tool_name).description


class TestDocstringMatchesConstants:
    def test_traffic_send_docstring(self):
        doc = _tool_description("traffic_send")
        for pattern, const_name in DOC_PATTERNS["traffic_send"]:
            m = re.search(pattern, doc)
            assert m, f"docstring 缺少上限表述: {pattern}"
            assert int(m.group(1)) == getattr(_TST, const_name), (
                f"docstring {int(m.group(1))} != 常量 {const_name}={getattr(_TST, const_name)}"
            )

    def test_mixed_traffic_send_docstring(self):
        doc = _tool_description("mixed_traffic_send")
        for pattern, const_name in DOC_PATTERNS["mixed_traffic_send"]:
            m = re.search(pattern, doc)
            assert m, f"docstring 缺少上限表述: {pattern}"
            assert int(m.group(1)) == getattr(_MTT, const_name), (
                f"docstring {int(m.group(1))} != 常量 {const_name}={getattr(_MTT, const_name)}"
            )


class TestPromptMatchesConstants:
    def _render(self):
        from jinja2 import Environment, FileSystemLoader
        env = Environment(loader=FileSystemLoader("src/prompts"))
        template = env.get_template("system_prompt.j2")
        return template.render(
            max_pps=_TST.MAX_PPS,
            max_duration_s=_TST.MAX_DURATION_S,
            max_packet_size=_TST.MAX_PACKET_SIZE,
            max_flow_count=_TST.MAX_FLOW_COUNT,
            max_iat_jitter_ms=_TST.MAX_IAT_JITTER_MS,
            pktgen_available=True, pktgen_dry_run=True,
            pktgen_host="10.99.80.222", pktgen_port="22022",
        )

    def test_prompt_contains_constant_limits(self):
        rendered = self._render()
        for value in (_TST.MAX_PPS, _TST.MAX_DURATION_S, _TST.MAX_PACKET_SIZE,
                      _TST.MAX_FLOW_COUNT, _TST.MAX_IAT_JITTER_MS):
            assert str(value) in rendered, f"提示词缺少上限值 {value}"

    def test_prompt_has_no_stale_limits(self):
        """提示词不得残留旧上限数字（200/10/512/50 的旧口径）。"""
        rendered = self._render()
        for stale in ("max 200", "512", "flow_count 50"):
            assert stale not in rendered, f"提示词残留过期上限表述: {stale}"

    def test_prompt_pktgen_duration_limit(self):
        """提示词含 Pktgen duration 上限 60000ms 口径。"""
        rendered = self._render()
        assert "60000" in rendered
