# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Closed-Loop Network Experiment Agent — a LangChain ReAct agent that autonomously explores traffic parameters to maximize ping RTT, with continuous background ping monitoring, web console, and strict safety constraints (allowlist, rate limits, HITL approval). Built with Python 3.11+, Scapy, LangChain, FastAPI, and DeepSeek API.

Also integrates Pktgen-DPDK (hardware packet generator) via vendored Lua compiler — the agent can escalate to hardware line-rate traffic generation when higher throughput is needed.

## Commands

```bash
# ── Testing ──────────────────────────────────────────────────────
uv run pytest tests/unit/ -v                        # Unit tests (no I/O)
uv run pytest tests/integration/ -v                 # Integration tests (real compiler, mock network)
uv run pytest tests/ -v                             # All tests (unit + integration)
uv run pytest --cov=src --cov-report=term-missing   # With coverage

# ── CLI Agent ────────────────────────────────────────────────────
# Dry-run (default) — compile Lua only, no traffic sent
uv run python src/main.py --target-ip 10.99.80.160 --max-iters 5

# Auto-approve — skip HITL prompts
uv run python src/main.py --target-ip 10.99.80.160 --max-iters 5 --auto-approve

# Pktgen live mode — actually send traffic to Pktgen hardware
uv run python src/main.py --target-ip 10.99.80.160 --pktgen-live --max-iters 5

# Custom attack parameters
uv run python src/main.py --target-ip 10.99.80.160 --duration 10 --pps 500 --pktgen-rate 80

# With PCAP profiling
uv run python src/main.py --target-ip 10.99.80.160 --pcap-path data/sample.pcapng

# ── Web Console ──────────────────────────────────────────────────
uv run uvicorn backend.server:app --host 0.0.0.0 --port 8000 --reload
# Open http://localhost:8000
```

## Architecture

```
User Request → LangChain V1.0 Agent (LangGraph StateGraph)
                 ├─ System prompt (src/prompts/system_prompt.j2)
                 ├─ 17 tools: 8 Scapy + 9 Pktgen-DPDK
                 │    ├─ Scapy: traffic_send, mixed_traffic_send, ping_rtt, ...
                 │    └─ Pktgen: pktgen_udp_flood → adapter.py → vendored
                 │         pktgen_agent/compiler/compile.py → Lua → TCP :22022
                 └─ HITL: interrupt() on traffic tools → Command(resume=...)
```

Two runtime modes: **CLI** (`src/main.py`, synchronous) and **Web** (`backend/server.py`, async WebSocket).

### Key Files

| File | Role |
|------|------|
| `src/agent/graph.py` | Builds agent via `create_agent()`, model config, system prompt rendering with template variables, DeepSeek reasoning_content monkey-patch |
| `src/agent/tools.py` | 17 `@tool`-decorated LangChain tools (8 Scapy + 9 Pktgen via `*PKTGEN_TOOLS`); HITL gates via `interrupt()` |
| `src/pktgen/adapter.py` | Pktgen adapter — wraps vendored `pktgen_agent` execution functions as `@tool` functions; enforces allowlist, HITL, RTT sampling, and synchronous wait (`_wait_for_attack`) |
| `src/main.py` | CLI entry — reads `experiment.json`, sets env vars for tool defaults, parses CLI args, runs HITL polling loop |
| `src/prompts/system_prompt.j2` | Jinja2 system prompt — ReAct protocol, Pktgen tool tables, parameter semantics, optimization strategy table, concrete examples |
| `src/config/experiment.json` | Single source of truth for defaults: target IP, max iters, attack params (duration, pps, packet_size, flow_count), pktgen params (rate, duration) |
| `src/config/allowlist.json` | Allowlisted target IPs |
| `pktgen_agent/compiler/compile.py` | Vendored SkillCompiler — reads `dsl/skills/*.yaml`, validates params, emits Lua |
| `pktgen_agent/tools/execute.py` | Vendored `execute_skill_dry_run()` / `execute_skill_live()` — compile→save→TCP |
| `pktgen_agent/client.py` | Vendored `PktgenClient` — TCP socket to Pktgen (default `topology.yaml → 10.99.80.222:22022`) |
| `dsl/skills/*.yaml` | 9 skill definitions (udp/tcp/icmp/arp flood, range_scan, packet_sequence, pcap_replay, stats_monitoring, safe_stop_and_reset) |
| `topology.yaml` | Pktgen host/port and MAC address (`dst_mac: f0:c4:78:4c:a5:55`) |
| `src/tools/ping_monitor.py` | Background ping subprocess + reader thread, thread-safe deque, `get_stats()` / `get_samples_since()` |
| `src/tools/mixed_traffic_tool.py` | Multi-protocol via JSON spec; `validate_traffic_spec()` auto-fills missing percentages |
| `backend/server.py` + `backend/experiment.py` | Web console — async FastAPI + WebSocket, queue-based HITL |

### Agent Tools (17 total)

| Category | Count | Tools |
|----------|:-----:|-------|
| Scapy (original) | 8 | `pcap_profile`, `start_ping_monitor`, `read_ping_stats`, `stop_ping_monitor`, `traffic_send`, `mixed_traffic_send`, `ping_rtt`, `log_result` |
| Pktgen (added) | 9 | `pktgen_udp_flood`, `pktgen_tcp_flood`, `pktgen_icmp_flood`, `pktgen_arp_flood`, `pktgen_range_scan`, `pktgen_packet_sequence`, `pktgen_pcap_replay`, `pktgen_stats_monitor`, `pktgen_stop_and_reset` |

HITL applies to traffic-generating tools (Scapy + Pktgen flood/scan/sequence/replay). `pktgen_stats_monitor` and `pktgen_stop_and_reset` skip HITL.

### Pktgen Adapter Architecture

```
LLM calls pktgen_udp_flood(rate=50, duration=5000)
  → adapter @tool
    → validate_target(dst_ip)         # allowlist
    → interrupt() HITL gate           # live mode only
    → execute_skill_live/dry_run()    # vendored engine
    → _wait_for_attack(duration)      # sync: sleep until traffic completes
    → _sample_rtt(t0)                 # capture RTT during attack window
    → _normalize_result()             # add summary + artifacts
```

Key adapter behaviors:
- **Default dry-run**: compile Lua only, no traffic sent. Use `--pktgen-live` for live.
- **Synchronous wait**: after live execution, sleeps for `duration` ms so `rtt_during` captures the full attack window (unlike original async Pktgen which returned immediately).
- **Auto-fill**: `mixed_traffic_send` fills missing stream percentages evenly.
- **Config-driven defaults**: tool defaults come from `experiment.json` → env vars → function signature.

### Configuration Flow

```
experiment.json  →  main.py sets env vars  →  tools.py reads at call time
     │                      │                          │
     │  "attack": {         │  ATK_DURATION_S=5        │  duration_s = env or 5
     │    "duration_s": 5   │  ATK_PPS=100             │  pps = env or 100
     │    "pps": 100        │                          │
     │    ...               │  PKTGEN_RATE=50          │  rate = env or 50
     │  }                   │                          │
     │  "pktgen": {         │                          │
     │    "rate": 50        │                          │
     │    "duration_ms":5000│                          │
     │  }                   │                          │
     └──────────────────────┘                          ┘
```

## Key Conventions

### Parameter Limits

| Parameter | Max | Constant |
|-----------|-----|----------|
| pps | 20000 | `MAX_PPS` |
| duration_s | 20 | `MAX_DURATION_S` |
| packet_size | 1024 | `MAX_PACKET_SIZE` |
| flow_count | 100 | `MAX_FLOW_COUNT` |
| iat_jitter_ms | 20 | `MAX_IAT_JITTER_MS` |
| mixed streams | 100 | `MAX_STREAMS` |
| Pktgen rate | 100% | skill YAML constraint |
| Pktgen duration | 60000 ms | capped by `_wait_for_attack` |

### Security Validation

All traffic tools enforce: allowlist (`validate_target`), no broadcast/multicast, no src_ip forgery. Pktgen tools additionally enforce `dst_ip` must be non-empty for skills in `_SKILLS_WITH_DST_IP`. `pktgen_pcap_replay` is exempt (PCAP embeds its own dst_ip) — system prompt warns about this.

### Test Organization

- `tests/unit/` — mock all I/O. `conftest.py` adds project root to `sys.path`.
- `tests/integration/` — real compiler, real config, mock network. `conftest.py` has session-scoped Pktgen availability check (auto-skips if unreachable).
- `tests/e2e/` — full agent loop tests.
- Test IPs: `10.99.80.160` for allowlist tests, `192.168.1.99` for rejection.
- `pyproject.toml` registers `unit`, `integration`, `slow` pytest markers.

### LLM / DeepSeek Integration

- `ChatOpenAI` → `https://api.deepseek.com`, model from `LLM_MODEL` env (default `deepseek-chat`).
- `reasoning_content` monkey-patch in `graph.py` preserves DeepSeek's thinking across multi-turn.
- API key from `DEEPSEEK_API_KEY` or `OPENAI_API_KEY` in `.env` (gitignored, use `.env_example` as template).

### PingMonitor (Singleton)

`get_ping_monitor()` returns the singleton; never instantiate directly. `main.py`'s `finally` block ensures cleanup. Tools auto-collect `rtt_during` during attack via `get_samples_since(t0)`.

### Important Constraints

- **Cross-platform**: detect via `sys.platform`, never hardcode OS-specific flags (see `docs/debugging/cross_platform.md`).
- **Import order**: Pktgen config uses functions (`is_dry_run()`, `get_pktgen_host()`) not module constants, because `main()` sets env vars AFTER imports are resolved.
- **Vendored Pktgen code** (`pktgen_agent/`, `dsl/`, `topology.yaml`) is at project root and kept in sync with the Lua project. Project root must be on `sys.path`.
- **`pyyaml`** is a core dependency (not transitive) — required by vendored compiler.
