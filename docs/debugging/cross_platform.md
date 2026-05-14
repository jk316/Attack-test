# Cross-Platform ping Command Differences

## Problem

`ping_rtt_tool.py` hardcoded Unix-style `ping -c <count> -W <timeout>`, causing zero-packet failures on Windows.

## Root Cause

The `ping` command has fundamentally different flags and output format on Linux vs Windows:

### Flag Differences

| Purpose | Linux/macOS | Windows |
|---------|-------------|---------|
| Packet count | `-c 4` | `-n 4` |
| Timeout | `-W 10` (seconds) | `-w 10000` (milliseconds) |

### Output Format Differences

**Linux**:
```
2 packets transmitted, 2 packets received, 0% packet loss
round-trip min/avg/max = 1.234/1.345/1.456 ms
```

**Windows**:
```
Packets: Sent = 4, Received = 4, Lost = 0 (0% loss),
Approximate round trip times in milli-seconds:
    Minimum = 3ms, Maximum = 8ms, Average = 5ms
```

## Solution

`src/tools/ping_rtt_tool.py`:

1. `build_ping_cmd()` — detects `sys.platform` and builds platform-appropriate command
2. `parse_ping_output()` — tries Windows regex patterns first, then Unix, for packet counts and RTT stats

## Lesson

Any CLI tool that shells out to system commands must:
- Detect the platform via `sys.platform` (never assume Linux)
- Handle both output formats in parsing logic
- Tests must not hardcode platform-specific flags (`-c` vs `-n`)
