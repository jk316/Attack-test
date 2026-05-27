"""LangChain tool wrappers for the closed-loop experiment agent.

Each tool is decorated with @tool so the LLM can call it via ReAct tool-calling.
The traffic_send tool includes a HITL gate via langgraph interrupt().
"""
from typing import Any

from langchain.tools import tool
from langgraph.types import interrupt

from src.tools.ping_rtt_tool import ping_rtt_tool
from src.tools.traffic_send_tool import traffic_send_tool
from src.tools.mixed_traffic_tool import mixed_traffic_send_tool
from src.tools.pcap_profile_tool import pcap_profile_tool, DEFAULT_COUNT_LIMIT
from src.tools.log_tool import log_tool


@tool
def ping_rtt(ip: str, count: int = 4, timeout: int = 10) -> dict[str, Any]:
    """Measure RTT to a target IP via ping.

    Args:
        ip: Target IP address (must be in allowlist).
        count: Number of ping packets (default 4).
        timeout: Timeout in seconds (default 10).

    Returns:
        Dict with avg_rtt_ms, loss_pct, packets_transmitted, packets_received.
    """
    return ping_rtt_tool(ip=ip, count=count, timeout=timeout)


@tool
def traffic_send(
    dst_ip: str,
    dst_port: int,
    duration_s: int = 5,
    pps: int = 100,
    packet_size: int = 64,
    flow_count: int = 1,
    iat_jitter_ms: int = 0,
) -> dict[str, Any]:
    """Send controlled traffic to a target. REQUIRES HUMAN APPROVAL.

    This tool pauses for human confirmation before sending any traffic.
    All parameters are clamped to safe limits internally.

    Args:
        dst_ip: Target IP address (must be in allowlist).
        dst_port: Target port (1-65535).
        duration_s: Send duration in seconds (max 10).
        pps: Packets per second (max 200).
        packet_size: Payload size in bytes (max 512).
        flow_count: Number of concurrent flows with unique sport (max 50).
        iat_jitter_ms: Random jitter on inter-packet interval in ms (max 20).

    Returns:
        Dict with success, params, packets_sent, elapsed_s, effective_pps.
    """
    params_display = {
        "dst_ip": dst_ip,
        "dst_port": dst_port,
        "duration_s": duration_s,
        "pps": pps,
        "packet_size": packet_size,
        "flow_count": flow_count,
        "iat_jitter_ms": iat_jitter_ms,
    }
    approval = interrupt({
        "message": "[HITL] Approve traffic send?",
        "params": params_display,
    })
    if not approval:
        return {"success": False, "error": "HITL rejected by operator"}

    return traffic_send_tool(
        dst_ip=dst_ip,
        dst_port=dst_port,
        duration_s=duration_s,
        pps=pps,
        packet_size=packet_size,
        flow_count=flow_count,
        iat_jitter_ms=iat_jitter_ms,
    )


@tool
def pcap_profile(pcap_path: str, count: int = DEFAULT_COUNT_LIMIT) -> dict[str, Any]:
    """Analyze a PCAP/PCAPng file and return traffic profile.

    Extracts: top destination IPs/ports, packet size histogram, inter-arrival
    time statistics, flow count estimates, and payload length statistics.
    Only traffic packets are profiled; TCP/ICMP are noted but ignored.

    Args:
        pcap_path: Path to the pcap or pcapng file.
        count: Maximum number of packets to read (default 50000).

    Returns:
        Dict with top_dst_ips, top_dst_ports, packet_size_hist, iat_ms_stats,
        flow_stats, payload_len_stats, and notes.
    """
    return pcap_profile_tool(pcap_path=pcap_path, count=count)


@tool
def log_result(log_path: str, iteration: int, params: dict, rtt: float, loss: float) -> dict[str, Any]:
    """Append experiment result to a JSONL log file.

    Args:
        log_path: Path to the JSONL log file.
        iteration: Current iteration number.
        params: The traffic parameters used in this iteration.
        rtt: Average RTT in milliseconds measured this iteration.
        loss: Packet loss percentage this iteration.

    Returns:
        Dict with success status.
    """
    entry = {"iteration": iteration, "params": params, "rtt": rtt, "loss": loss}
    return log_tool(log_path=log_path, entry=entry)


@tool
def mixed_traffic_send(
    dst_ip: str,
    traffic_spec_json: str,
    duration_s: int = 5,
    pps: int = 100,
) -> dict[str, Any]:
    """Send mixed-protocol traffic to a target using a traffic specification.
    REQUIRES HUMAN APPROVAL.

    Use this tool to send multiple concurrent traffic streams with different
    protocols (TCP, UDP, DNS, ICMP, etc.) in a single experiment iteration.
    Prefer this over traffic_send when you want to mix protocols or need
    protocol-level control (TCP flags, DNS queries, ICMP types).

    Args:
        dst_ip: Target IP address (must be in allowlist). IP.dst in the JSON
                is ignored — this value overwrites it for safety.
        traffic_spec_json: JSON string describing traffic streams. See the
                system prompt for the exact schema (streams, protocol_stack,
                fields, percentage).
        duration_s: Send duration in seconds (max 10).
        pps: Total packets per second across all streams (max 200).

    Returns:
        Dict with success, params, packets_sent (total + per_stream),
        elapsed_s, effective_pps.
    """
    params_display = {
        "dst_ip": dst_ip,
        "duration_s": duration_s,
        "pps": pps,
    }
    approval = interrupt({
        "message": "[HITL] Approve mixed traffic send?",
        "params": params_display,
    })
    if not approval:
        return {"success": False, "error": "HITL rejected by operator"}

    return mixed_traffic_send_tool(
        dst_ip=dst_ip,
        traffic_spec_json=traffic_spec_json,
        duration_s=duration_s,
        pps=pps,
    )


# Tool list for create_agent
EXPERIMENT_TOOLS = [pcap_profile, traffic_send, mixed_traffic_send, ping_rtt, log_result]
