"""Traffic Send Tool - Sends compliant UDP traffic to allowlist targets"""
import random
import socket
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


def _create_raw_socket() -> socket.socket | None:
    """Create a raw IP socket with IP_HDRINCL for pre-built packet sending.

    Returns None if permission is denied (caller should fall back to UDP socket
    or Scapy).
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_RAW)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
        return sock
    except (PermissionError, OSError):
        return None


def _create_udp_sockets(flow_count: int) -> list[socket.socket] | None:
    """Create regular UDP sockets (one per flow), no admin needed.

    Returns None if binding fails.
    """
    socks: list[socket.socket] = []
    try:
        for f in range(flow_count):
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.bind(("", 1024 + f))
            sock.setblocking(False)
            socks.append(sock)
        return socks
    except (PermissionError, OSError):
        for s in socks:
            s.close()
        return None


def validate_params(
    dst_ip: str,
    dst_port: int,
    duration_s: int,
    pps: int,
    packet_size: int,
    flow_count: int,
    iat_jitter_ms: int,
    src_ip: Optional[str]
) -> tuple[int, int, int, int, int]:
    """Validate and clamp parameters to safe limits.

    Security-critical violations (target, port, src_ip) raise ValueError.
    Numeric parameters are clamped to their allowed ranges.
    """
    # Target validation (reuses allowlist / broadcast / multicast checks)
    validate_target(dst_ip)

    if not (1 <= dst_port <= 65535):
        raise ValueError(f"Invalid dst_port: {dst_port}")

    if pps <= 0:
        raise ValueError(f"pps must be > 0, got {pps}")
    clamped_pps = min(pps, MAX_PPS)

    if duration_s <= 0:
        raise ValueError(f"duration_s must be > 0, got {duration_s}")
    clamped_duration_s = min(duration_s, MAX_DURATION_S)

    if packet_size <= 0:
        raise ValueError(f"packet_size must be > 0, got {packet_size}")
    clamped_packet_size = min(packet_size, MAX_PACKET_SIZE)

    if flow_count <= 0:
        raise ValueError(f"flow_count must be > 0, got {flow_count}")
    clamped_flow_count = min(flow_count, MAX_FLOW_COUNT)

    if iat_jitter_ms < 0:
        raise ValueError(f"iat_jitter_ms must be >= 0, got {iat_jitter_ms}")
    clamped_iat_jitter_ms = min(iat_jitter_ms, MAX_IAT_JITTER_MS)

    if src_ip is not None:
        raise ValueError("src_ip forgery is not allowed")

    return (
        clamped_duration_s,
        clamped_pps,
        clamped_packet_size,
        clamped_flow_count,
        clamped_iat_jitter_ms,
    )


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

    # Validate and clamp parameters (raises ValueError on security violation)
    duration_s, pps, packet_size, flow_count, iat_jitter_ms = validate_params(
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

    # ── Pre-build packet bytes for raw socket path ───────────────
    prebuilt: list[bytes] = []
    for f in range(flow_count):
        sport = 1024 + f
        pkt = IP(dst=dst_ip) / UDP(dport=dst_port, sport=sport) / Raw(load=payload)
        prebuilt.append(bytes(pkt))

    # ── 3-tier send: raw socket → UDP sockets → Scapy ────────────
    raw_sock = _create_raw_socket()
    udp_socks: list[socket.socket] | None = None
    send_mode: str  # "raw" | "udp" | "scapy"

    if raw_sock is not None:
        send_mode = "raw"
    else:
        udp_socks = _create_udp_sockets(flow_count)
        if udp_socks is not None:
            send_mode = "udp"
        else:
            send_mode = "scapy"

    # For UDP socket mode, just send payload (OS adds IP+UDP headers)
    if send_mode == "udp":
        # prebuilt[0] contains full IP packet bytes — extract just the Raw payload
        # IP header = 20 bytes, UDP header = 8 bytes
        payload_only = prebuilt[0][28:]  # strip IP+UDP headers
        prebuilt_payloads = [payload_only] * flow_count

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
                flow_id = flow_idx % flow_count
                per_flow[flow_id] += 1
                total_sent += 1
                flow_idx += 1

                if send_mode == "raw":
                    raw_sock.sendto(prebuilt[flow_id], (dst_ip, 0))  # type: ignore[union-attr]
                elif send_mode == "udp":
                    udp_socks[flow_id].sendto(  # type: ignore[index]
                        prebuilt_payloads[flow_id], (dst_ip, dst_port)
                    )
                else:
                    sport = 1024 + flow_id
                    pkt = IP(dst=dst_ip) / UDP(dport=dst_port, sport=sport) / Raw(load=payload)
                    send(pkt, verbose=verbose, iface=iface)

                # Schedule next packet with jitter
                jitter_s = random.uniform(-iat_jitter_ms, iat_jitter_ms) / 1000.0
                next_send = time.time() + max(base_inter + jitter_s, 0)
            else:
                # Brief yield to avoid busy-wait
                time.sleep(0.0001)

    except KeyboardInterrupt:
        pass
    finally:
        if raw_sock is not None:
            raw_sock.close()
        if udp_socks is not None:
            for s in udp_socks:
                s.close()

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
        "send_mode": send_mode,
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
