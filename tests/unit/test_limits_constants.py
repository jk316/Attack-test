"""上限常量宪法绑定测试（008-T003）。

断言各模块上限常量与宪法「附加约束·参数上限」数值一致，防止未来误改上限。
宪法：pps=20000、duration=20s、packet_size=1024、flow_count=100、
iat_jitter_ms=20、mixed streams=100；Pktgen rate≤100%/duration≤60000ms
为跨层约束（由 T008/T009 覆盖）。
"""

import importlib

# src/tools/__init__.py 遮蔽同名模块属性，模块须经 importlib 取
traffic_send_tool = importlib.import_module("src.tools.traffic_send_tool")
mixed_traffic_tool = importlib.import_module("src.tools.mixed_traffic_tool")


class TestScapyLimitsConstants:
    def test_max_pps(self):
        assert traffic_send_tool.MAX_PPS == 20000

    def test_max_duration_s(self):
        assert traffic_send_tool.MAX_DURATION_S == 20

    def test_max_packet_size(self):
        assert traffic_send_tool.MAX_PACKET_SIZE == 1024

    def test_max_flow_count(self):
        assert traffic_send_tool.MAX_FLOW_COUNT == 100

    def test_max_iat_jitter_ms(self):
        assert traffic_send_tool.MAX_IAT_JITTER_MS == 20


class TestMixedTrafficLimitsConstants:
    def test_max_streams(self):
        assert mixed_traffic_tool.MAX_STREAMS == 100

    def test_max_pps_matches_constitution(self):
        assert mixed_traffic_tool.MAX_PPS == 20000

    def test_max_duration_s_matches_constitution(self):
        assert mixed_traffic_tool.MAX_DURATION_S == 20

    def test_max_iat_jitter_ms_matches_constitution(self):
        assert mixed_traffic_tool.MAX_IAT_JITTER_MS == 20


class TestPktgenCrossLayerLimits:
    """Pktgen 上限为跨层约束（宪法附加约束）：rate≤100%、duration≤60000ms。"""

    def test_duration_limit_constant(self):
        from src.pktgen.adapter import DURATION_LIMIT_MS
        assert DURATION_LIMIT_MS == 60000
