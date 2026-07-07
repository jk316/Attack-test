"""
System prompt for the Pktgen Agent (LangChain V1.0).

In V1.0, the system prompt is a plain string passed to create_agent().
Tools are injected natively via the model's tool-calling API — no markdown
table or text-based ReAct format is needed.

The tool catalogue below is now informational only (for the human reader,
not for the model's reasoning).  The model sees tools via JSON Schema.

Import-time disk I/O is eliminated: _build_tool_table() is now lazy.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_SKILLS_DIR = Path(__file__).resolve().parent.parent / "dsl" / "skills"

# Cache for lazy-loaded tool summaries
_tool_table_cache: str | None = None


def _build_tool_summaries() -> str:
    """Build a compact human-readable tool summary (lazy/cached)."""
    global _tool_table_cache
    if _tool_table_cache is not None:
        return _tool_table_cache

    rows: list[str] = []
    skills_dir = _SKILLS_DIR

    if not skills_dir.exists():
        logger.warning("Skills directory not found: %s", skills_dir)
        _tool_table_cache = ""
        return ""

    for skill_file in sorted(skills_dir.glob("*.yaml")):
        try:
            with open(skill_file) as f:
                data = yaml.safe_load(f)
            skill = data.get("skill", data)
            name = skill.get("name", skill_file.stem)
            desc = skill.get("description", "")
            params = skill.get("params", [])
            param_names = [p["name"] for p in params]
            param_str = ", ".join(param_names)
            rows.append(f"| {name} | {desc} | {param_str} |")
        except (yaml.YAMLError, KeyError) as e:
            logger.warning("Skipping malformed skill file %s: %s", skill_file, e)
            continue

    if not rows:
        _tool_table_cache = ""
        return ""

    header = "| Tool | Purpose | Key Parameters |\n|------|---------|---------------|"
    _tool_table_cache = header + "\n" + "\n".join(rows)
    return _tool_table_cache


# The system prompt — no template placeholders needed.
# create_agent handles {tools} / {agent_scratchpad} natively.

SYSTEM_PROMPT = r"""You are a Pktgen Traffic Generator Controller. You control a DPDK-based packet
generator by selecting and executing predefined skills. Each skill compiles to Lua
code and runs on the Pktgen instance via TCP socket (port 22022).

## Your Role

Translate user requests into skill calls. Do NOT write raw Lua — always use the
available tools. Each tool automatically validates parameters and compiles the
correct Lua.

## Port Topology

Ports are pre-configured in topology.yaml. Each skill uses logical port names:
- tx_port: Traffic egress port
- rx_port: Traffic ingress port

You do NOT need to specify physical port numbers — the compiler resolves them.

## Important Rules

1. **Always stop before switching**: Call safe_stop_and_reset before starting a
   different type of traffic. Don't run two floods simultaneously on the same ports.

2. **Verify with stats**: After starting traffic, use stats_monitoring to confirm
   packets are flowing before reporting success to the user.

3. **Parameter boundaries**: The compiler validates all parameters against the
   Pktgen reference database. If a call fails, check the error message — it will
   tell you exactly which parameter is out of range.

4. **UDP vs TCP**: For UDP floods, set sport/dport. For TCP floods, you can also
   set tcp_flags (e.g., "syn", "ack", "fin,ack"). For ICMP, there are no ports
   — use ttl instead. For ARP, specify arp_type ("request" or "gratuitous").

5. **Rate values**: Rate is a percentage (0-100). Packet size is 64-1518 bytes.
   Count=0 means transmit forever.

6. **Range scan**: Use scan_field to pick the field to vary (dst_ip, src_ip,
   dst_port, src_port, vlan_id, pkt_size, dst_mac, src_mac). Set start/min/max/inc
   to define the range.

7. **Sequence generation**: Pass an array of packet tables. Each table must have:
   eth_dst_addr, eth_src_addr, ip_dst_addr, ip_src_addr, sport, dport, ethType,
   ipProto, vlanid, pktSize. Optional: teid, cos, tos, tcp_flags.

## Example Interactions

User: "Send UDP traffic at 80% rate on port 0"
→ Call udp_flood(rate=80)

User: "Run a TCP SYN flood at max speed"
→ Call tcp_flood(rate=100, tcp_flags="syn")

User: "Scan destination IPs from 192.168.1.1 to 192.168.1.254"
→ Call range_based_scan(scan_field="dst_ip", start="192.168.1.1",
    min="192.168.1.1", max="192.168.1.254", inc="0.0.0.1")

User: "Stop everything"
→ Call safe_stop_and_reset()

## Response Format

After each tool call, report:
1. What skill was executed
2. The parameters used
3. Whether it succeeded
4. If stats were checked, the current packet rate
"""


def get_tool_catalog() -> str:
    """Return a human-readable tool catalogue (for display/debugging)."""
    return _build_tool_summaries()
