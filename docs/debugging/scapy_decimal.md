# Scapy pcapng Decimal Serialization Bug

## Problem

`pcap_profile_tool.py` crashed with `TypeError: Object of type Decimal is not JSON serializable` when reading `.pcapng` files.

## Root Cause

Scapy's `rdpcap()` returns `packet.time` as `decimal.Decimal` when reading pcapng format (not pcap). The `calculate_iat()` function performed arithmetic on these values:

```python
iat_ms = (pkts[i].time - pkts[i-1].time) * 1000  # Decimal result
```

The `Decimal` type propagated through `statistics.mean()` and `percentile()` into the final result dict, where `json.dumps()` rejected it.

## Solution

`src/tools/pcap_profile_tool.py` line 46 — explicit `float()` cast:

```python
iat_ms = (float(pkts[i].time) - float(pkts[i-1].time)) * 1000
```

## Lesson

- `rdpcap()` returns different numeric types depending on file format (pcap vs pcapng)
- Always validate JSON serializability of tool return values — mock-based tests won't catch type errors from real data
- When processing Scapy packet attributes, cast to `float` at the boundary (on read)
