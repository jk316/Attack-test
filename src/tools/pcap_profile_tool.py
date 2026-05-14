"""PCAP Profile Tool - Analyzes pcap files and generates traffic profile"""
import json
from pathlib import Path
from typing import Dict, Any, List, Tuple
from collections import defaultdict
import statistics

try:
    from scapy.utils import RawPcapReader
    from scapy.layers.inet import IP, UDP
    from scapy.utils import rdpcap
    HAS_SCAPY = True
except ImportError:
    HAS_SCAPY = False

# Default count limit to avoid memory issues
DEFAULT_COUNT_LIMIT = 50000


def calculate_iat(packets: List) -> List[float]:
    """
    Calculate Inter-Arrival Time (IAT) for packets.

    IAT is calculated per (dst_ip, dst_port) flow as the time delta
    between consecutive packets to the same destination.

    Returns:
        List of IAT values in milliseconds
    """
    iats = []
    # Group packets by (dst_ip, dst_port)
    flow_packets = defaultdict(list)

    for pkt in packets:
        if not pkt.haslayer(IP) or not pkt.haslayer(UDP):
            continue
        dst_ip = pkt[IP].dst
        dst_port = pkt[UDP].dport
        flow_packets[(dst_ip, dst_port)].append(pkt)

    # Calculate IAT for each flow
    for flow, pkts in flow_packets.items():
        # Sort by time
        pkts.sort(key=lambda p: p.time)
        for i in range(1, len(pkts)):
            iat_ms = (float(pkts[i].time) - float(pkts[i-1].time)) * 1000
            iats.append(iat_ms)

    return iats


def calculate_flow_count(packets: List, idle_timeout: int = 30) -> int:
    """
    Calculate approximate flow count.

    Flow is defined by 5-tuple: (src_ip, src_port, dst_ip, dst_port, proto)
    Flows are considered distinct if separated by more than idle_timeout seconds.

    Args:
        packets: List of packets
        idle_timeout: Timeout in seconds to distinguish flows

    Returns:
        Approximate flow count
    """
    flows = defaultdict(list)

    for pkt in packets:
        if not pkt.haslayer(IP) or not pkt.haslayer(UDP):
            continue

        src_ip = pkt[IP].src
        dst_ip = pkt[IP].dst
        src_port = pkt[UDP].sport
        dst_port = pkt[UDP].dport

        # Create flow key
        flow_key = (src_ip, src_ip, dst_ip, dst_port, 'UDP')

        flows[flow_key].append(pkt.time)

    # Count flows with idle timeout consideration
    flow_count = 0
    for flow_key, times in flows.items():
        times.sort()
        if not times:
            continue
        # Start with one flow
        flow_count += 1
        # Add additional flows for gaps > idle_timeout
        for i in range(1, len(times)):
            if times[i] - times[i-1] > idle_timeout:
                flow_count += 1

    return flow_count


def parse_packet_size(size: int) -> str:
    """Categorize packet size into buckets"""
    if size <= 64:
        return "64"
    elif size <= 128:
        return "128"
    elif size <= 256:
        return "256"
    elif size <= 512:
        return "512"
    elif size <= 1024:
        return "1024"
    else:
        return "other"


def percentile(data: List[float], p: float) -> float:
    """Calculate percentile of data"""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    idx = int(len(sorted_data) * p / 100)
    if idx >= len(sorted_data):
        idx = len(sorted_data) - 1
    return sorted_data[idx]


def pcap_profile_tool(pcap_path: str, count: int = DEFAULT_COUNT_LIMIT) -> Dict[str, Any]:
    """
    Read pcap/pcapng file and output traffic profile as structured JSON.

    Args:
        pcap_path: Path to pcap file
        count: Maximum number of packets to read (default 50000)

    Returns:
        Dict containing:
        - top_dst_ips: List of top destination IPs
        - top_dst_ports: List of top destination ports
        - packet_size_hist: Histogram of packet sizes
        - iat_ms_stats: IAT statistics (mean, p50, p90)
        - flow_stats: Flow statistics (approx_flow_count, timeout_s)
        - payload_len_stats: Payload length statistics
        - notes: Any parsing issues or notes
    """
    result = {
        "top_dst_ips": [],
        "top_dst_ports": [],
        "packet_size_hist": {},
        "iat_ms_stats": {"mean": 0.0, "p50": 0.0, "p90": 0.0},
        "flow_stats": {"approx_flow_count": 0, "timeout_s": 30},
        "payload_len_stats": {"mean": 0.0, "p50": 0.0, "p90": 0.0},
        "notes": "UDP-only traffic profile. IAT calculated per (dst_ip, dst_port) flow."
    }

    # Check if scapy is available
    if not HAS_SCAPY:
        result["notes"] = "Scapy not available, cannot parse pcap"
        return result

    # Check if file exists
    path = Path(pcap_path)
    if not path.exists():
        result["notes"] = f"File not found: {pcap_path}"
        return result

    try:
        # Read packets using rdpcap with count limit
        # rdpcap returns a PacketList, we iterate and limit
        all_packets = []
        packet_count = 0

        for pkt in rdpcap(str(pcap_path)):
            if count > 0 and packet_count >= count:
                break
            all_packets.append(pkt)
            packet_count += 1

        if packet_count >= count:
            result["notes"] += f" Limited to {count} packets."

        # Filter to UDP only
        udp_packets = []
        tcp_count = 0
        icmp_count = 0
        other_count = 0

        for pkt in all_packets:
            if not pkt.haslayer(IP):
                other_count += 1
                continue
            if pkt.haslayer(UDP):
                udp_packets.append(pkt)
            elif pkt.haslayer("TCP"):
                tcp_count += 1
            elif pkt.haslayer("ICMP"):
                icmp_count += 1
            else:
                other_count += 1

        # Build notes about traffic types
        notes_parts = [result["notes"]]
        if tcp_count > 0:
            notes_parts.append(f"Ignored {tcp_count} TCP packets.")
        if icmp_count > 0:
            notes_parts.append(f"Ignored {icmp_count} ICMP packets.")
        if other_count > 0:
            notes_parts.append(f"Ignored {other_count} non-IP packets.")
        result["notes"] = " ".join(notes_parts)

        if not udp_packets:
            return result

        # Calculate top destination IPs
        dst_ip_counts = defaultdict(int)
        dst_port_counts = defaultdict(int)
        packet_sizes = []
        payload_lengths = []

        for pkt in udp_packets:
            dst_ip = pkt[IP].dst
            dst_port = pkt[UDP].dport
            dst_ip_counts[dst_ip] += 1
            dst_port_counts[dst_port] += 1
            packet_sizes.append(len(pkt))
            # Payload length
            if pkt.haslayer(UDP):
                payload_len = len(pkt[UDP].payload)
                payload_lengths.append(payload_len)

        # Top destination IPs (sorted by count, top 10)
        sorted_ips = sorted(dst_ip_counts.items(), key=lambda x: x[1], reverse=True)
        result["top_dst_ips"] = [ip for ip, _ in sorted_ips[:10]]

        # Top destination ports
        sorted_ports = sorted(dst_port_counts.items(), key=lambda x: x[1], reverse=True)
        result["top_dst_ports"] = [port for port, _ in sorted_ports[:10]]

        # Packet size histogram
        size_hist = defaultdict(int)
        for size in packet_sizes:
            bucket = parse_packet_size(size)
            size_hist[bucket] += 1

        # Normalize to probabilities
        total_size = len(packet_sizes)
        result["packet_size_hist"] = {
            bucket: round(count / total_size, 4) if total_size > 0 else 0
            for bucket, count in size_hist.items()
        }

        # IAT statistics
        iats = calculate_iat(udp_packets)
        if iats:
            result["iat_ms_stats"] = {
                "mean": round(statistics.mean(iats), 4),
                "p50": round(percentile(iats, 50), 4),
                "p90": round(percentile(iats, 90), 4)
            }

        # Flow statistics
        result["flow_stats"] = {
            "approx_flow_count": calculate_flow_count(udp_packets, idle_timeout=30),
            "timeout_s": 30
        }

        # Payload length statistics
        if payload_lengths:
            result["payload_len_stats"] = {
                "mean": round(statistics.mean(payload_lengths), 4),
                "p50": round(percentile(payload_lengths, 50), 4),
                "p90": round(percentile(payload_lengths, 90), 4)
            }

    except Exception as e:
        result["notes"] = f"Error parsing pcap: {str(e)}"

    return result


if __name__ == "__main__":
    # CLI test
    import sys
    if len(sys.argv) > 1:
        result = pcap_profile_tool(sys.argv[1])
        print(json.dumps(result, indent=2))
    else:
        print("Usage: python pcap_profile_tool.py <pcap_file>")