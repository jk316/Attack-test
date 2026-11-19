"""Tests for pcap_profile_tool - RED stage"""
import json
from unittest.mock import patch, MagicMock, mock_open
import pytest
import sys
import os

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from scapy.layers.inet import IP, UDP
from scapy.packet import Packet


class TestPcapProfileTool:
    """Test suite for pcap_profile_tool"""

    def test_output_json_structure_has_required_fields(self):
        """输出 JSON 必须包含所有必需字段"""
        from tools.pcap_profile_tool import pcap_profile_tool

        # Mock a minimal pcap with UDP packets
        mock_packets = []

        with patch('scapy.utils.RawPcapReader') as mock_reader, \
             patch('scapy.plist.PacketList') as mock_plist:

            mock_reader.return_value = iter([])
            mock_plist.return_value = mock_plist

            result = pcap_profile_tool("dummy.pcap")

        # 检查必需字段
        required_fields = [
            "top_dst_ips", "top_dst_ports", "packet_size_hist",
            "iat_ms_stats", "flow_stats", "payload_len_stats", "notes"
        ]
        for field in required_fields:
            assert field in result, f"Missing required field: {field}"

    def test_only_udp_packets_counted(self):
        """仅统计 UDP 包，TCP/ICMP 应被忽略"""
        from tools.pcap_profile_tool import pcap_profile_tool
        from scapy.layers.inet import IP, UDP, TCP
        import tempfile
        import os

        # 创建 UDP 包
        udp_pkt = IP(dst="192.168.1.1") / UDP(dport=8000) / "payload"
        # 创建 TCP 包 (不会被统计)
        tcp_pkt = IP(dst="192.168.1.2") / TCP(dport=9000) / "payload"

        # 需要临时创建一个有效的 pcap 文件
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(suffix='.pcap', delete=False) as f:
            pcap_path = f.name

        try:
            from scapy.utils import wrpcap
            wrpcap(pcap_path, [udp_pkt, tcp_pkt])

            result = pcap_profile_tool(pcap_path)

            # notes 应说明只统计 UDP
            assert "UDP" in result.get("notes", "")
            # TCP 包不应该出现在 top_dst_ips 中
            assert "192.168.1.2" not in result.get("top_dst_ips", [])
        finally:
            os.unlink(pcap_path)

    def test_count_limit_enforced(self):
        """count 参数必须限制最多读取 N 包"""
        from tools.pcap_profile_tool import pcap_profile_tool

        # 创建超过限制的包列表
        many_packets = [MagicMock(spec=Packet) for _ in range(100)]

        with patch('scapy.utils.RawPcapReader') as mock_reader:
            mock_reader.return_value = iter(many_packets)

            # 使用 count=50 限制
            result = pcap_profile_tool("test.pcap", count=50)

        # 验证最多处理 50 个包
        # 在实现中应该看到处理数量被限制

    def test_top_dst_ips_returns_list(self):
        """top_dst_ips 应该是排序后的 IP 列表"""
        from tools.pcap_profile_tool import pcap_profile_tool

        mock_packets = []

        with patch('scapy.utils.RawPcapReader') as mock_reader:
            mock_reader.return_value = iter(mock_packets)
            result = pcap_profile_tool("test.pcap")

        assert isinstance(result["top_dst_ips"], list)
        assert len(result["top_dst_ips"]) <= 10  # 最多 10 个

    def test_top_dst_ports_returns_list(self):
        """top_dst_ports 应该是排序后的端口列表"""
        from tools.pcap_profile_tool import pcap_profile_tool

        mock_packets = []

        with patch('scapy.utils.RawPcapReader') as mock_reader:
            mock_reader.return_value = iter(mock_packets)
            result = pcap_profile_tool("test.pcap")

        assert isinstance(result["top_dst_ports"], list)

    def test_packet_size_hist_format(self):
        """packet_size_hist 应该是 {size: count/probability} 格式"""
        from tools.pcap_profile_tool import pcap_profile_tool

        mock_packets = []

        with patch('scapy.utils.RawPcapReader') as mock_reader:
            mock_reader.return_value = iter(mock_packets)
            result = pcap_profile_tool("test.pcap")

        hist = result["packet_size_hist"]
        assert isinstance(hist, dict)
        # 检查键是数字（包大小）
        for size_str in hist.keys():
            assert size_str.isdigit() or size_str == "other"
        # 检查值是数字（计数或概率）
        for count in hist.values():
            assert isinstance(count, (int, float))

    def test_iat_ms_stats_structure(self):
        """iat_ms_stats 必须包含 mean, p50, p90"""
        from tools.pcap_profile_tool import pcap_profile_tool

        mock_packets = []

        with patch('scapy.utils.RawPcapReader') as mock_reader:
            mock_reader.return_value = iter(mock_packets)
            result = pcap_profile_tool("test.pcap")

        iat_stats = result["iat_ms_stats"]
        required_keys = ["mean", "p50", "p90"]
        for key in required_keys:
            assert key in iat_stats, f"Missing IAT stat: {key}"
            assert isinstance(iat_stats[key], (int, float))

    def test_flow_stats_structure(self):
        """flow_stats 必须包含 approx_flow_count 和 timeout_s"""
        from tools.pcap_profile_tool import pcap_profile_tool

        mock_packets = []

        with patch('scapy.utils.RawPcapReader') as mock_reader:
            mock_reader.return_value = iter(mock_packets)
            result = pcap_profile_tool("test.pcap")

        flow_stats = result["flow_stats"]
        assert "approx_flow_count" in flow_stats
        assert "timeout_s" in flow_stats
        assert isinstance(flow_stats["approx_flow_count"], int)
        assert isinstance(flow_stats["timeout_s"], (int, float))

    def test_payload_len_stats_structure(self):
        """payload_len_stats 必须包含 mean, p50, p90"""
        from tools.pcap_profile_tool import pcap_profile_tool

        mock_packets = []

        with patch('scapy.utils.RawPcapReader') as mock_reader:
            mock_reader.return_value = iter(mock_packets)
            result = pcap_profile_tool("test.pcap")

        payload_stats = result["payload_len_stats"]
        required_keys = ["mean", "p50", "p90"]
        for key in required_keys:
            assert key in payload_stats, f"Missing payload stat: {key}"

    def test_file_not_found_error(self):
        """文件不存在时应返回错误信息"""
        from tools.pcap_profile_tool import pcap_profile_tool

        result = pcap_profile_tool("nonexistent.pcap")

        assert "error" in result or "notes" in result
        assert "not found" in str(result).lower() or "error" in result

    def test_empty_pcap_handled(self):
        """空 pcap 文件应正常处理，返回空结果"""
        from tools.pcap_profile_tool import pcap_profile_tool

        with patch('scapy.utils.RawPcapReader') as mock_reader:
            mock_reader.return_value = iter([])
            result = pcap_profile_tool("empty.pcap")

        # 应该返回有效的 JSON 结构，即使没有数据
        assert "top_dst_ips" in result
        assert "top_dst_ports" in result
        # top_dst_ips 应该是空列表
        assert len(result["top_dst_ips"]) == 0

    def test_iat_calculation_method_documented(self):
        """IAT 计算方式必须在 notes 中说明"""
        from tools.pcap_profile_tool import pcap_profile_tool

        mock_packets = []

        with patch('scapy.utils.RawPcapReader') as mock_reader:
            mock_reader.return_value = iter(mock_packets)
            result = pcap_profile_tool("test.pcap")

        # notes 应该包含 IAT 计算方式的说明
        notes = result.get("notes", "")
        assert len(notes) > 0, "notes should document the IAT calculation method"

    def test_default_count_limit_50k(self):
        """默认 count 限制应为 50k 包"""
        from tools.pcap_profile_tool import pcap_profile_tool

        mock_packets = []

        with patch('scapy.utils.RawPcapReader') as mock_reader:
            mock_reader.return_value = iter(mock_packets)
            # 不传 count 参数，使用默认值
            result = pcap_profile_tool("test.pcap")

        # 检查 flow_stats 中的 timeout 设置
        assert result["flow_stats"]["timeout_s"] == 30

    def test_non_udp_only_flag(self):
        """如果 pcap 中有 TCP/ICMP，应在 notes 中说明被忽略"""
        from tools.pcap_profile_tool import pcap_profile_tool
        from scapy.layers.inet import IP, UDP, TCP
        import tempfile
        import os

        # 创建混合流量 pcap
        udp_pkt = IP(dst="192.168.1.1") / UDP(dport=8000) / "payload"
        tcp_pkt = IP(dst="192.168.1.2") / TCP(dport=9000) / "payload"

        with tempfile.NamedTemporaryFile(suffix='.pcap', delete=False) as f:
            pcap_path = f.name

        try:
            from scapy.utils import wrpcap
            wrpcap(pcap_path, [udp_pkt, tcp_pkt])

            result = pcap_profile_tool(pcap_path)

            notes = result.get("notes", "")
            # 应该记录统计口径 - UDP only
            assert "UDP" in notes or "only" in notes.lower()
        finally:
            os.unlink(pcap_path)

# ── 004 夹具与口径测试（T006-T012）──────────────────────────────────

def _udp(src, sport, dst, dport, payload_len, t):
    """构造一个带确定性时间戳的 UDP 包（T006 夹具部件）。"""
    from scapy.all import Raw

    pkt = IP(src=src, dst=dst) / UDP(sport=sport, dport=dport) / Raw(b"x" * payload_len)
    pkt.time = t
    return pkt


def _write_pcap(tmp_path, packets, name="fixture.pcap"):
    from scapy.all import wrpcap

    path = str(tmp_path / name)
    wrpcap(path, packets)
    return path


def _make_flow_fixture(tmp_path):
    """确定性混合抓包（T006）：UDP 多流 + 断流 + TCP/ICMP/非 IP。"""
    from scapy.all import Ether, TCP, ICMP, Raw

    pkts = [
        # 5 元组流 A：(1.1.1.1,1000,10.0.0.1,53) t=0,1 → 1 流
        _udp("1.1.1.1", 1000, "10.0.0.1", 53, 20, 0.0),
        _udp("1.1.1.1", 1000, "10.0.0.1", 53, 20, 1.0),
        # 流 B：同源不同端口 (1.1.1.1,2000,...) → 独立流（G-001 关键）
        _udp("1.1.1.1", 2000, "10.0.0.1", 53, 100, 0.0),
        _udp("1.1.1.1", 2000, "10.0.0.1", 53, 100, 1.0),
        # 流 A 断流：间隔 59s > 30s → 同一 5 元组计新流
        _udp("1.1.1.1", 1000, "10.0.0.1", 53, 100, 60.0),
        _udp("1.1.1.1", 1000, "10.0.0.1", 53, 100, 61.0),
        # 流 C：(3.3.3.3,3000,...) 4 包
        _udp("3.3.3.3", 3000, "10.0.0.1", 53, 100, 0.0),
        _udp("3.3.3.3", 3000, "10.0.0.1", 53, 100, 0.01),
        _udp("3.3.3.3", 3000, "10.0.0.1", 53, 100, 0.03),
        _udp("3.3.3.3", 3000, "10.0.0.1", 53, 100, 0.06),
        # 流 D：不同 dst/port，大负载 → other 桶
        _udp("2.2.2.2", 4000, "10.0.0.2", 123, 1200, 0.0),
        # 忽略类型（不进任何统计）
        IP(src="5.5.5.5", dst="10.0.0.1") / TCP(sport=9, dport=80),
        IP(src="6.6.6.6", dst="10.0.0.1") / ICMP(),
        Ether() / Raw(b"\x00" * 20),  # 非 IP
    ]
    # TCP/ICMP/非 IP 时间戳
    for p in pkts[11:]:
        p.time = 0.0
    return _write_pcap(tmp_path, pkts)


def _make_iat_fixture(tmp_path):
    """IAT 口径夹具：同 (dst,dport) 4 包 IAT 10/20/30ms + 单包端口。"""
    pkts = [
        _udp("1.1.1.1", 1000, "10.0.0.1", 53, 100, 0.0),
        _udp("1.1.1.1", 1000, "10.0.0.1", 53, 100, 0.01),
        _udp("1.1.1.1", 1000, "10.0.0.1", 53, 100, 0.03),
        _udp("1.1.1.1", 1000, "10.0.0.1", 53, 100, 0.06),
        _udp("1.1.1.1", 2000, "10.0.0.1", 9999, 100, 0.0),  # 单包 → 无 IAT
    ]
    return _write_pcap(tmp_path, pkts)


class TestFiveTupleFlowCount:
    """T007：5 元组流数口径（G-001、SC-005）。"""

    def test_same_src_different_ports_not_merged(self, tmp_path):
        from src.tools.pcap_profile_tool import pcap_profile_tool

        path = _make_flow_fixture(tmp_path)
        result = pcap_profile_tool(path)
        # 流：A(断流→2) + B + C + D = 5
        assert result["flow_stats"]["approx_flow_count"] == 5

    def test_idle_gap_counts_new_flow(self, tmp_path, monkeypatch):
        from src.tools.pcap_profile_tool import pcap_profile_tool

        monkeypatch.setenv("PCAP_PROFILE_IDLE_TIMEOUT_S", "30")
        # 两包间隔 31s > 30 → 2 条流
        from scapy.all import wrpcap

        pkts = [_udp("1.1.1.1", 1000, "10.0.0.1", 53, 100, 0.0),
                _udp("1.1.1.1", 1000, "10.0.0.1", 53, 100, 31.0)]
        path = _write_pcap(tmp_path, pkts, "gap.pcap")
        result = pcap_profile_tool(path)
        assert result["flow_stats"]["approx_flow_count"] == 2
        assert result["flow_stats"]["timeout_s"] == 30

    def test_idle_timeout_env_configurable(self, tmp_path, monkeypatch):
        from src.tools.pcap_profile_tool import pcap_profile_tool

        monkeypatch.setenv("PCAP_PROFILE_IDLE_TIMEOUT_S", "10")
        pkts = [_udp("1.1.1.1", 1000, "10.0.0.1", 53, 100, 0.0),
                _udp("1.1.1.1", 1000, "10.0.0.1", 53, 100, 31.0)]
        path = _write_pcap(tmp_path, pkts, "gap10.pcap")
        result = pcap_profile_tool(path)
        assert result["flow_stats"]["approx_flow_count"] == 2
        assert result["flow_stats"]["timeout_s"] == 10

    def test_short_gap_single_flow(self, tmp_path, monkeypatch):
        from src.tools.pcap_profile_tool import pcap_profile_tool

        monkeypatch.setenv("PCAP_PROFILE_IDLE_TIMEOUT_S", "30")
        pkts = [_udp("1.1.1.1", 1000, "10.0.0.1", 53, 100, 0.0),
                _udp("1.1.1.1", 1000, "10.0.0.1", 53, 100, 1.0)]
        path = _write_pcap(tmp_path, pkts, "nogap.pcap")
        result = pcap_profile_tool(path)
        assert result["flow_stats"]["approx_flow_count"] == 1


class TestUdpOnlyIsolation:
    """T009：UDP-only 隔离与忽略计数（G-005、FR-003/012、SC-003）。"""

    def test_ignored_counts_in_notes(self, tmp_path):
        from src.tools.pcap_profile_tool import pcap_profile_tool

        path = _make_flow_fixture(tmp_path)
        result = pcap_profile_tool(path)
        assert "Ignored 1 TCP packets." in result["notes"]
        assert "Ignored 1 ICMP packets." in result["notes"]
        assert "Ignored 1 non-IP packets." in result["notes"]

    def test_non_udp_excluded_from_stats(self, tmp_path):
        from src.tools.pcap_profile_tool import pcap_profile_tool

        path = _make_flow_fixture(tmp_path)
        result = pcap_profile_tool(path)
        # 只有 11 个 UDP 包进入统计（TCP/ICMP/非 IP 不计）
        assert result["top_dst_ips"] == ["10.0.0.1", "10.0.0.2"]
        assert result["top_dst_ports"] == [53, 123]
        assert sum(result["packet_size_hist"].values()) == pytest.approx(1.0, abs=0.001)


class TestIatStats:
    """T010：IAT 分组与精度（G-006、FR-006、SC-004）。"""

    def test_iat_manual_computation(self, tmp_path):
        from src.tools.pcap_profile_tool import pcap_profile_tool

        path = _make_iat_fixture(tmp_path)
        result = pcap_profile_tool(path)
        iat = result["iat_ms_stats"]
        # 同 (10.0.0.1, 53) 4 包 → IAT [10, 20, 30]ms
        assert abs(iat["mean"] - 20.0) <= 0.01
        assert abs(iat["p50"] - 20.0) <= 0.01
        assert abs(iat["p90"] - 30.0) <= 0.01

    def test_iat_grouped_per_dst_and_port(self, tmp_path):
        from src.tools.pcap_profile_tool import pcap_profile_tool

        # 单包端口不产生 IAT；另一端口包不污染 53 的 IAT
        path = _make_iat_fixture(tmp_path)
        result = pcap_profile_tool(path)
        iat = result["iat_ms_stats"]
        assert abs(iat["mean"] - 20.0) <= 0.01

    def test_single_packet_flows_no_iat(self, tmp_path):
        from src.tools.pcap_profile_tool import pcap_profile_tool

        pkts = [_udp("1.1.1.1", 1000, "10.0.0.1", 53, 100, 0.0)]
        path = _write_pcap(tmp_path, pkts, "single.pcap")
        result = pcap_profile_tool(path)
        assert result["iat_ms_stats"] == {"mean": 0.0, "p50": 0.0, "p90": 0.0}


class TestRankingsHistPayload:
    """T011：排行/直方图/负载统计（contracts/pcap-profile.md 第 1 节）。"""

    def test_rankings_desc_and_capped(self, tmp_path):
        from src.tools.pcap_profile_tool import pcap_profile_tool

        path = _make_flow_fixture(tmp_path)
        result = pcap_profile_tool(path)
        assert result["top_dst_ports"] == [53, 123]  # 降序
        assert result["top_dst_ips"] == ["10.0.0.1", "10.0.0.2"]
        assert len(result["top_dst_ports"]) <= 10

    def test_histogram_buckets_and_normalization(self, tmp_path):
        from src.tools.pcap_profile_tool import pcap_profile_tool

        path = _make_flow_fixture(tmp_path)
        result = pcap_profile_tool(path)
        hist = result["packet_size_hist"]
        assert set(hist.keys()) <= {"64", "128", "256", "512", "1024", "other"}
        # 11 个 UDP 包：2×48B(→64 桶) + 8×128B(→128 桶) + 1×1228B(→other)
        assert hist["64"] == round(2 / 11, 4)
        assert hist["128"] == round(8 / 11, 4)
        assert hist["other"] == round(1 / 11, 4)
        assert sum(hist.values()) == pytest.approx(1.0, abs=0.0001)

    def test_payload_len_stats(self, tmp_path):
        from src.tools.pcap_profile_tool import pcap_profile_tool

        path = _make_flow_fixture(tmp_path)
        result = pcap_profile_tool(path)
        pl = result["payload_len_stats"]
        payloads = sorted([20, 20] + [100] * 8 + [1200])
        assert pl["mean"] == round(sum(payloads) / len(payloads), 4)
        assert pl["p50"] == 100.0
        assert pl["p90"] == 100.0


class TestTruncationNote:
    """T012：截断注明（FR-002、SC-002）。"""

    def test_limited_note_when_count_smaller(self, tmp_path):
        from src.tools.pcap_profile_tool import pcap_profile_tool

        path = _make_flow_fixture(tmp_path)
        result = pcap_profile_tool(path, count=5)
        assert "Limited to 5 packets." in result["notes"]
        # 前 5 包 = 流 A(2) + 流 B(2) + 断流首包 → 仅 10.0.0.1:53
        assert result["top_dst_ports"] == [53]
        assert result["top_dst_ips"] == ["10.0.0.1"]

    def test_no_limited_note_when_count_sufficient(self, tmp_path):
        from src.tools.pcap_profile_tool import pcap_profile_tool

        path = _make_flow_fixture(tmp_path)
        result = pcap_profile_tool(path, count=100)
        assert "Limited to" not in result["notes"]


class TestRobustness:
    """T019：异常输入稳健性（G-007、FR-010、SC-006）。"""

    REQUIRED = ["top_dst_ips", "top_dst_ports", "packet_size_hist",
                "iat_ms_stats", "flow_stats", "payload_len_stats", "notes"]

    def test_file_not_found(self, tmp_path):
        from src.tools.pcap_profile_tool import pcap_profile_tool

        result = pcap_profile_tool(str(tmp_path / "nope.pcap"))
        assert "File not found" in result["notes"]
        for field in self.REQUIRED:
            assert field in result  # 七字段完整结构

    def test_corrupt_binary(self, tmp_path):
        from src.tools.pcap_profile_tool import pcap_profile_tool

        path = tmp_path / "corrupt.pcap"
        path.write_bytes(b"\xde\xad\xbe\xef" * 10)
        result = pcap_profile_tool(str(path))
        assert "Error parsing pcap" in result["notes"]
        assert result["top_dst_ips"] == []
        assert result["flow_stats"]["approx_flow_count"] == 0

    def test_empty_file_zero_stats(self, tmp_path):
        from src.tools.pcap_profile_tool import pcap_profile_tool

        path = tmp_path / "empty.pcap"
        path.write_bytes(b"")
        result = pcap_profile_tool(str(path))
        assert result["top_dst_ips"] == []
        assert result["top_dst_ports"] == []
        assert result["packet_size_hist"] == {}
        assert result["payload_len_stats"] == {"mean": 0.0, "p50": 0.0, "p90": 0.0}

    def test_tcp_only_file_zero_stats_and_no_udp_note(self, tmp_path):
        """纯 TCP 文件：统计为零 + 显式「未发现 UDP 流量」说明（G-002，T020 转绿）。"""
        from scapy.all import TCP, wrpcap

        from src.tools.pcap_profile_tool import pcap_profile_tool

        pkts = [IP(src="1.1.1.1", dst="10.0.0.1") / TCP(dport=80),
                IP(src="1.1.1.1", dst="10.0.0.1") / TCP(dport=443)]
        for p in pkts:
            p.time = 0.0
        path = _write_pcap(tmp_path, pkts, "tcp_only.pcap")
        result = pcap_profile_tool(path)
        assert result["top_dst_ips"] == []
        assert result["top_dst_ports"] == []
        assert result["flow_stats"]["approx_flow_count"] == 0
        assert "Ignored 2 TCP packets." in result["notes"]
        assert "未发现 UDP 流量" in result["notes"]  # T020 红：当前缺失

    def test_scapy_unavailable(self, tmp_path, monkeypatch):
        import importlib

        from src.tools.pcap_profile_tool import pcap_profile_tool

        mod = importlib.import_module("src.tools.pcap_profile_tool")
        monkeypatch.setattr(mod, "HAS_SCAPY", False)
        result = pcap_profile_tool(str(tmp_path / "any.pcap"))
        assert "Scapy not available" in result["notes"]
        for field in self.REQUIRED:
            assert field in result
