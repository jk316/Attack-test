"""Traffic Send Tool - Sends compliant UDP traffic to allowlist targets"""
import random
import time
from typing import Dict, Any, Optional

from .ping_rtt_tool import validate_target, ALLOWLIST

try:
    from scapy.all import IP, UDP, Raw, send
    HAS_SCAPY = True
except ImportError:
    HAS_SCAPY = False

# Parameter upper limits
MAX_PPS = 20000
MAX_DURATION_S = 20
MAX_PACKET_SIZE = 1024
MAX_FLOW_COUNT = 100
MAX_IAT_JITTER_MS = 20


def validate_params(
    dst_ip: str,
    dst_port: int,
    duration_s: int,
    pps: int,
    packet_size: int,
    flow_count: int,
    iat_jitter_ms: int,
    src_ip: Optional[str]
) -> None:
    """Validate all parameters meet security constraints. Raises ValueError on violation."""
    # Target validation (reuses allowlist / broadcast / multicast checks)
    validate_target(dst_ip)

    if not (1 <= dst_port <= 65535):
        raise ValueError(f"Invalid dst_port: {dst_port}")

    if pps <= 0:
        raise ValueError(f"pps must be > 0, got {pps}")
    if pps > MAX_PPS:
        raise ValueError(f"pps ({pps}) exceeds maximum ({MAX_PPS})")

    if duration_s <= 0:
        raise ValueError(f"duration_s must be > 0, got {duration_s}")
    if duration_s > MAX_DURATION_S:
        raise ValueError(f"duration_s ({duration_s}) exceeds maximum ({MAX_DURATION_S})")

    if packet_size <= 0:
        raise ValueError(f"packet_size must be > 0, got {packet_size}")
    if packet_size > MAX_PACKET_SIZE:
        raise ValueError(f"packet_size ({packet_size}) exceeds maximum ({MAX_PACKET_SIZE})")

    if flow_count <= 0:
        raise ValueError(f"flow_count must be > 0, got {flow_count}")
    if flow_count > MAX_FLOW_COUNT:
        raise ValueError(f"flow_count ({flow_count}) exceeds maximum ({MAX_FLOW_COUNT})")

    if iat_jitter_ms < 0:
        raise ValueError(f"iat_jitter_ms must be >= 0, got {iat_jitter_ms}")
    if iat_jitter_ms > MAX_IAT_JITTER_MS:
        raise ValueError(f"iat_jitter_ms ({iat_jitter_ms}) exceeds maximum ({MAX_IAT_JITTER_MS})")

    if src_ip is not None:
        raise ValueError("src_ip forgery is not allowed")


def traffic_send_tool(
    dst_ip: str,
    dst_port: int,
    duration_s: int = 5,
    pps: int = 100,
    packet_size: int = 64,
    flow_count: int = 1,
    iat_jitter_ms: int = 0,
    src_ip: Optional[str] = None,
    iface: Optional[str] = None,
    verbose: bool = False
) -> Dict[str, Any]:
    """
    Send compliant UDP traffic to an allowlist target using Scapy L3 send().

    Args:
        dst_ip: Target IP address (must be in allowlist).
        dst_port: Target UDP port.
        duration_s: Send duration in seconds (max 20).
        pps: Packets per second across all flows (max 20000).
        packet_size: Payload size in bytes (max 1024).
        flow_count: Number of concurrent flows, each with unique sport (max 100).
        iat_jitter_ms: Random jitter on inter-packet interval in ms (max 20).
        src_ip: Must be None — source IP forgery is forbidden.
        iface: Optional network interface for send().
        verbose: Enable Scapy verbose output (default False).

    Returns:
        Dict with: success, params, packets_sent, elapsed_s, effective_pps, errors
    """
    if not HAS_SCAPY:
        raise ImportError("Scapy is required for traffic_send_tool")

    # Validate all parameters (raises ValueError on violation)
    validate_params(
        dst_ip, dst_port, duration_s, pps, packet_size,
        flow_count, iat_jitter_ms, src_ip
    )

    params = {
        "dst_ip": dst_ip,
        "dst_port": dst_port,
        "duration_s": duration_s,
        "pps": pps,
        "packet_size": packet_size,
        "flow_count": flow_count,
        "iat_jitter_ms": iat_jitter_ms,
    }

    # Build payload once
    payload = b"\x00" * packet_size
    base_inter = 1.0 / pps  # seconds between consecutive packets

    # Per-flow counters
    per_flow = {flow_id: 0 for flow_id in range(flow_count)}
    total_sent = 0
    flow_idx = 0

    start_time = time.time()
    deadline = start_time + duration_s
    next_send = start_time

    try:
        while time.time() < deadline:
            now = time.time()
            if now >= next_send:
                # Round-robin across flows
                sport = 1024 + (flow_idx % flow_count)
                pkt = IP(dst=dst_ip) / UDP(dport=dst_port, sport=sport) / Raw(load=payload)

                send(pkt, verbose=verbose, iface=iface)

                flow_id = flow_idx % flow_count
                per_flow[flow_id] += 1
                total_sent += 1
                flow_idx += 1

                # Schedule next packet with jitter
                jitter_s = random.uniform(-iat_jitter_ms, iat_jitter_ms) / 1000.0
                next_send = time.time() + max(base_inter + jitter_s, 0)
            else:
                # Brief yield to avoid busy-wait
                time.sleep(0.0001)

    except KeyboardInterrupt:
        pass

    elapsed = time.time() - start_time
    effective_pps = round(total_sent / elapsed, 2) if elapsed > 0 else 0.0

    return {
        "success": True,
        "params": params,
        "packets_sent": {
            "total": total_sent,
            "per_flow": per_flow,
        },
        "elapsed_s": round(elapsed, 4),
        "effective_pps": effective_pps,
        "errors": [],
    }


if __name__ == "__main__":
    import sys, json
    if len(sys.argv) < 3:
        print("Usage: python traffic_send_tool.py <dst_ip> <dst_port> [pps] [duration_s]")
        sys.exit(1)
    result = traffic_send_tool(
        dst_ip=sys.argv[1],
        dst_port=int(sys.argv[2]),
        pps=int(sys.argv[3]) if len(sys.argv) > 3 else 10,
        duration_s=int(sys.argv[4]) if len(sys.argv) > 4 else 2,
    )
    print(json.dumps(result, indent=2))
