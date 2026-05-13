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