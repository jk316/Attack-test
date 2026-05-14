"""Ping RTT Tool - Measures round-trip time to allowlist hosts"""
import json
import re
import subprocess
import sys
from typing import Dict, Any, List
from pathlib import Path

# Default allowlist - should be overridden via config
DEFAULT_ALLOWLIST = [
    "10.99.80.160"
]

ALLOWLIST_PATH = Path(__file__).parent.parent / "config" / "allowlist.json"


def load_allowlist() -> list[str]:
    """Load allowlist from config file"""
    if ALLOWLIST_PATH.exists():
        try:
            with open(ALLOWLIST_PATH, "r") as f:
                data = json.load(f)
                return data.get("hosts", DEFAULT_ALLOWLIST)
        except (json.JSONDecodeError, IOError):
            pass
    return DEFAULT_ALLOWLIST


ALLOWLIST = load_allowlist()


def is_valid_ip(ip: str) -> bool:
    """Validate IP address format"""
    pattern = r"^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$"
    return bool(re.match(pattern, ip))


def is_broadcast(ip: str) -> bool:
    """Check if IP is broadcast address"""
    return ip.endswith(".255")


def is_multicast(ip: str) -> bool:
    """Check if IP is multicast address (224.0.0.0 - 239.255.255.255)"""
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    first = int(parts[0])
    return 224 <= first <= 239


def is_allowlisted(ip: str) -> bool:
    """Check if IP is in allowlist"""
    return ip in ALLOWLIST


def validate_target(ip: str) -> None:
    """Validate target meets all security requirements"""
    if not ALLOWLIST:
        raise ValueError("allowlist is empty")

    if not is_valid_ip(ip):
        raise ValueError(f"Invalid IP format: {ip}")

    if is_broadcast(ip):
        raise ValueError(f"Broadcast address not allowed: {ip}")

    if is_multicast(ip):
        raise ValueError(f"Multicast address not allowed: {ip}")

    if not is_allowlisted(ip):
        raise ValueError(f"Target {ip} not in allowlist")


def build_ping_cmd(ip: str, count: int, timeout: int) -> List[str]:
    """Build platform-appropriate ping command."""
    if sys.platform == "win32":
        # Windows: ping -n <count> -w <timeout_ms> <ip>
        return ["ping", "-n", str(count), "-w", str(timeout * 1000), ip]
    else:
        # Linux/macOS: ping -c <count> -W <timeout_s> <ip>
        return ["ping", "-c", str(count), "-W", str(timeout), ip]


def parse_ping_output(output: str) -> Dict[str, Any]:
    """Parse ping command output to extract RTT and loss stats.
    Handles both Unix and Windows ping output formats.
    """
    result = {
        "success": False,
        "avg_rtt_ms": 0.0,
        "loss_pct": 100.0,
        "packets_transmitted": 0,
        "packets_received": 0,
        "raw_output": output
    }

    # Windows output format:
    #   Packets: Sent = 3, Received = 3, Lost = 0 (0% loss),
    #   Minimum = 3ms, Maximum = 8ms, Average = 5ms
    win_sent = re.search(r"Sent\s*=\s*(\d+)", output)
    win_recv = re.search(r"Received\s*=\s*(\d+)", output)
    win_rtt = re.search(r"Average\s*=\s*([\d.]+)\s*ms", output)

    # Unix output format:
    #   2 packets transmitted, 2 packets received, 0% packet loss
    #   round-trip min/avg/max = 1.234/1.345/1.456 ms
    unix_sent = re.search(r"(\d+)\s+packets transmitted", output)
    unix_recv = re.search(r"(\d+)\s+packets received", output)
    unix_rtt = re.search(r"round-trip.*?=\s*([\d.]+)/([\d.]+)/([\d.]+)", output)

    # Loss percentage — common pattern for both: "N% loss"
    loss_match = re.search(r"(\d+)%\s*(?:packet\s*)?loss", output)
    if loss_match:
        result["loss_pct"] = float(loss_match.group(1))

    # Packet counts (try Windows first, then Unix)
    if win_sent:
        result["packets_transmitted"] = int(win_sent.group(1))
    elif unix_sent:
        result["packets_transmitted"] = int(unix_sent.group(1))

    if win_recv:
        result["packets_received"] = int(win_recv.group(1))
    elif unix_recv:
        result["packets_received"] = int(unix_recv.group(1))

    # RTT (try Windows first, then Unix)
    if win_rtt:
        result["avg_rtt_ms"] = float(win_rtt.group(1))
        result["success"] = True
    elif unix_rtt:
        result["avg_rtt_ms"] = float(unix_rtt.group(2))
        result["success"] = True
    elif "0 packets received" in output or "Lost = " in output:
        # Check if all packets were lost (may still have sent count)
        sent = result["packets_transmitted"]
        recv = result["packets_received"]
        if sent > 0 and recv == 0:
            result["avg_rtt_ms"] = float('inf')
            result["success"] = True

    return result


def ping_rtt_tool(ip: str, count: int = 4, timeout: int = 10) -> Dict[str, Any]:
    """
    Execute ping against an allowlist target and return RTT statistics.

    Args:
        ip: Target IP address
        count: Number of ping packets (default 4)
        timeout: Timeout in seconds (default 10)

    Returns:
        Dict with keys: success, avg_rtt_ms, loss_pct, packets_transmitted,
                        packets_received, raw_output
    """
    # Security validation
    validate_target(ip)

    # Build platform-appropriate ping command
    cmd = build_ping_cmd(ip, count, timeout)

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout + 5
        )

        output = proc.stdout if proc.stdout else proc.stderr

        if proc.returncode != 0 and "packets received" not in output and "Received" not in output:
            return {
                "success": False,
                "error": f"Ping failed with return code {proc.returncode}",
                "raw_output": output
            }

        return parse_ping_output(output)

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "Ping timeout expired",
            "avg_rtt_ms": float('inf'),
            "loss_pct": 100.0
        }
    except FileNotFoundError:
        return {
            "success": False,
            "error": "ping command not found",
            "avg_rtt_ms": 0.0,
            "loss_pct": 100.0
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "avg_rtt_ms": 0.0,
            "loss_pct": 100.0
        }


if __name__ == "__main__":
    # CLI test
    import sys
    if len(sys.argv) > 1:
        result = ping_rtt_tool(sys.argv[1])
        print(json.dumps(result, indent=2))
    else:
        print("Usage: python ping_rtt_tool.py <ip>")