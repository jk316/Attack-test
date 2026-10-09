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

# Custom attack parameters (defaults from experiment.json: duration=10s, pps=100)
uv run python src/main.py --target-ip 10.99.80.160 --duration 10 --pps 500 --pktgen-rate 80

# With PCAP profiling
uv run python src/main.py --target-ip 10.99.80.160 --pcap-path data/sample.pcapng

# TRex attack catalog exploration — agent generates ≥10 attack scripts with
# Chinese annotations (dry-run only: no traffic, no HITL) and saves the catalog
# summary to output/trex_attack_catalog_<timestamp>.md
uv run python src/main.py --trex-explore
uv run python src/main.py --trex-explore --catalog-target 15 --max-iters 60

# Per-run exploration direction — free-form text injected into the catalog
# prompt (no traffic, no HITL; omit for generic exploration)
uv run python src/main.py --trex-explore --explore-direction "重点探索DNS放大攻击和TCP SYN洪水"

# ── Web Console ──────────────────────────────────────────────────
uv run uvicorn backend.server:app --host 0.0.0.0 --port 8000 --reload
# Open http://localhost:8000
```

## Architecture

### Agent Runtime (three modes)

```
┌─ CLI experiment (src/main.py, default) ─────────────────────────┐
│  Synchronous loop: graph.invoke() → poll interrupts → input()   │
│  HITL: blocking input("Approve? (y/n): ")                       │
└─────────────────────────────────────────────────────────────────┘

┌─ CLI TRex explore (src/main.py --trex-explore) ─────────────────┐
│  Attack catalog generation: tool set restricted to the 2 TRex   │
│  tools (write + dry-run syntax check), forced dry-run.          │
│  Zero traffic, zero HITL — runs fully autonomous; final summary │
│  saved to output/trex_attack_catalog_<timestamp>.md             │
└─────────────────────────────────────────────────────────────────┘

┌─ Web Console (backend/server.py + backend/experiment.py) ───────┐
│  Async WebSocket loop: graph.ainvoke() → ws.send_json()         │
│  HITL: asyncio.Queue — frontend sends hitl_response via WS      │
│  ExperimentManager bridges LangGraph's sync interrupt() with    │
│  async WebSocket message passing                                │
└─────────────────────────────────────────────────────────────────┘
```

All modes use the same `build_graph()` → `CompiledStateGraph` with `MemorySaver` checkpointer. `build_graph(max_iters, no_improve_limit, mode)` selects the prompt template (`system_prompt.j2` vs `trex_catalog_prompt.j2`) and tool set (`EXPERIMENT_TOOLS` vs `TREX_TOOLS`); the caller passes the graph's superstep budget via invoke config (`_recursion_limit()` in main.py).

### Core Agent Loop

```
User Request → LangChain V1.0 Agent (LangGraph StateGraph)
                 ├─ System prompt (src/prompts/system_prompt.j2)
                 ├─ 19 tools: 8 Scapy + 9 Pktgen-DPDK + 2 TRex
                 │    ├─ Scapy: traffic_send, mixed_traffic_send, ping_rtt, ...
                 │    ├─ Pktgen: pktgen_udp_flood → adapter.py → vendored
                 │    │         pktgen_agent/compiler/compile.py → Lua → TCP :22022
                 │    └─ TRex: write_python_file → run_python_file → subprocess
                 │              (client generates .py → runs against Trexserver)
                 └─ HITL: interrupt() on traffic tools → Command(resume=...)
```

**Convergence / early-stop**: the loop stops after `no_improve_limit` (default 5) consecutive rounds without RTT improvement. This value is threaded through `main.py` (CLI `--no-improve-limit` / `experiment.json`) → `build_graph(max_iters, no_improve_limit)` → `system_prompt.j2`; it is not hardcoded in the tools.

### Web Console Architecture

```
Frontend (static HTML/JS/CSS)
  │  app.js — WebSocket client, renders agent messages + HITL buttons
  │  index.html — single-page console UI
  │  style.css — dark-themed console styling
  │
  ▼ WebSocket /ws/{client_id}
FastAPI (backend/server.py)
  │  POST /api/upload/pcap — PCAP file upload
  │  GET  /api/experiment/status
  │
  ▼
ExperimentManager (backend/experiment.py)
  │  Async bridge: graph.ainvoke() → extract messages → ws.send_json()
  │  HITL via asyncio.Queue: frontend click → approve(True/False) → queue
  │  Message conversion: _msg_to_dict() extracts role/content/tool_calls
```

### Key Files

| File | Role |
|------|------|
| `src/agent/graph.py` | Builds agent via `create_agent()`, model config, system prompt rendering with template variables, DeepSeek reasoning_content monkey-patch |
| `src/agent/tools.py` | 19 `@tool`-decorated LangChain tools (8 Scapy + 9 Pktgen via `*PKTGEN_TOOLS` + 2 TRex via `*TREX_TOOLS`); HITL gates via `interrupt()` |
| `src/agent/state.py` | Agent state definition |
| `src/pktgen/adapter.py` | Pktgen adapter — wraps vendored `pktgen_agent` execution functions as `@tool` functions; enforces allowlist, HITL, RTT sampling, synchronous wait (`_wait_for_attack`), and **auto-fills eth_dst_addr** in `pktgen_packet_sequence` from `topology.yaml` |
| `src/trex/tools.py` | TRex client tools — `write_python_file` (write `.py` into `trex_scripts/` sandbox + parse-only syntax check) and `run_python_file` (subprocess execution + allowlist/HITL/timeout gates). Narrowed `write`+`bash` that lets the LLM generate arbitrary TRex client scripts |
| `src/trex/config.py` | TRex config getters — `get_trex_host()`/`get_trex_port()`/`is_trex_dry_run()`/`get_trex_scripts_dir()`/`get_trex_timeout_s()`, re-reading env each call |
| `src/main.py` | CLI entry — reads `experiment.json`, sets env vars for tool defaults, parses CLI args, runs HITL polling loop with `VerboseCallback` for LLM I/O logging |
| `src/prompts/system_prompt.j2` | Jinja2 system prompt — ReAct protocol, Pktgen tool tables, parameter semantics, optimization strategy table, concrete examples |
| `src/prompts/trex_catalog_prompt.j2` | Jinja2 prompt for `--trex-explore` mode — plan→generate→summarize protocol, `cat_` filename rule, mandatory Chinese annotation block per script, catalog summary table format |
| `src/config/experiment.json` | Single source of truth for defaults: target IP, max iters, attack params (duration=10s, pps, packet_size, flow_count), pktgen params (rate, duration_ms) |
| `src/config/allowlist.json` | Allowlisted target IPs |
| `src/tools/ping_monitor.py` | Background ping subprocess + reader thread, thread-safe deque, `get_stats()` / `get_samples_since()`. Dual backend: **fping -Q** (preferred, 10 probes/s with per-second summaries) or **system ping** (fallback) |
| `src/tools/rtt_window.py` | `build_rtt_observation()` — enriches tool results with `rtt_during`, `attack_window`, `observation_window` fields |
| `src/tools/traffic_send_tool.py` | Scapy UDP traffic generator with parameter clamping |
| `src/tools/mixed_traffic_tool.py` | Multi-protocol via JSON spec; `validate_traffic_spec()` auto-fills missing percentages |
| `src/tools/pcap_profile_tool.py` | PCAP/PCAPng analysis — extracts IPs, ports, packet size histograms, IAT stats |
| `src/tools/ping_rtt_tool.py` | Single-shot ping RTT measurement + `validate_target()` allowlist enforcement |
| `src/tools/log_tool.py` | JSONL experiment logging |
| `backend/server.py` | FastAPI app — WebSocket endpoint, REST API, static file serving, PCAP upload |
| `backend/experiment.py` | `ExperimentManager` — async bridge between LangGraph agent and WebSocket frontend; manages experiment lifecycle, HITL queue, message streaming |
| `frontend/index.html` + `app.js` + `style.css` | Web console UI — single-page app with dark theme, real-time message display, HITL approve/reject buttons |
| `pktgen_agent/compiler/compile.py` | Vendored SkillCompiler — reads `dsl/skills/*.yaml`, validates params, emits Lua |
| `pktgen_agent/tools/execute.py` | Vendored `execute_skill_dry_run()` / `execute_skill_live()` — compile→save→TCP |
| `pktgen_agent/client.py` | Vendored `PktgenClient` — TCP socket to Pktgen (default `topology.yaml → 10.99.80.222:22022`) |
| `dsl/skills/*.yaml` | 9 skill definitions (udp/tcp/icmp/arp flood, range_scan, packet_sequence, pcap_replay, stats_monitoring, safe_stop_and_reset) |
| `topology.yaml` | Pktgen host/port, port mappings, and MAC address (`dst_mac: f0:c4:78:4c:a5:55`) |

### Agent Tools (19 total)

| Category | Count | Tools |
|----------|:-----:|-------|
| Scapy (original) | 8 | `pcap_profile`, `start_ping_monitor`, `read_ping_stats`, `stop_ping_monitor`, `traffic_send`, `mixed_traffic_send`, `ping_rtt`, `log_result` |
| Pktgen (added) | 9 | `pktgen_udp_flood`, `pktgen_tcp_flood`, `pktgen_icmp_flood`, `pktgen_arp_flood`, `pktgen_range_scan`, `pktgen_packet_sequence`, `pktgen_pcap_replay`, `pktgen_stats_monitor`, `pktgen_stop_and_reset` |
| TRex (added) | 2 | `write_python_file`, `run_python_file` |

HITL applies to traffic-generating tools (Scapy + Pktgen flood/scan/sequence/replay + TRex `run_python_file` in live mode). `pktgen_stats_monitor` and `pktgen_stop_and_reset` skip HITL. TRex tools default to dry-run (write + syntax-check only); `--trex-live` enables execution. `--trex-explore` is a dedicated catalog mode: the agent gets ONLY the 2 TRex tools (write + dry-run check), TRex dry-run is forced (mutually exclusive with `--trex-live`), so the whole loop runs with zero traffic and zero HITL; the final summary is persisted to `output/trex_attack_catalog_<timestamp>.md` (timestamp keeps each run's report from overwriting the previous one) and scripts land in `trex_scripts/cat_*.py`.

### Pktgen Adapter Architecture

```
LLM calls pktgen_udp_flood(rate=50, duration=5000)
  → adapter @tool
    → validate_target(dst_ip)         # allowlist (skipped for arp_flood, pcap_replay)
    → interrupt() HITL gate           # live mode only
    → execute_skill_live/dry_run()    # vendored engine
    → _wait_for_attack(duration)      # sync: sleep ms→s, capped at 60s
    → _sample_rtt(t0)                 # capture RTT during attack window
    → _normalize_result()             # add summary + artifacts, truncate lua_code
```

Adapter behaviors:
- **Default dry-run**: compile Lua only, no traffic sent. Use `--pktgen-live` for live.
- **Synchronous wait**: after live execution, sleeps for `duration` ms so `rtt_during` captures the full attack window.
- **Auto-fill eth_dst_addr**: `pktgen_packet_sequence` detects fabricated MAC addresses (missing, empty, or all-zeros/ones pattern like `00:00:00:00:00:01`) and replaces them with the real `dst_mac` from `topology.yaml`. This prevents the LLM from inventing MAC addresses it doesn't know.
- **Auto-fill percentages**: `mixed_traffic_send` fills missing stream percentages evenly.
- **Config-driven defaults**: tool defaults come from `experiment.json` → env vars → function signature.

### Allowlist & HITL Gates

| Skill | Allowlist (`dst_ip`) | HITL Gate |
|-------|:--------------------:|:---------:|
| `udp_flood` | ✅ | ✅ |
| `tcp_flood` | ✅ | ✅ |
| `icmp_flood` | ✅ | ✅ |
| `arp_flood` | ❌ (L2, no IP) | ✅ |
| `range_based_scan` | ✅ | ✅ |
| `packet_sequence_generation` | ✅ | ✅ |
| `pcap_replay` | ❌ (uses PCAP's own dst) | ✅ |
| `stats_monitoring` | N/A | ❌ |
| `safe_stop_and_reset` | N/A | ❌ |

### Configuration Flow

```
experiment.json  →  main.py sets env vars  →  tools.py reads at call time
     │                      │                          │
     │  "attack": {         │  ATK_DURATION_S=10       │  duration_s = env or 10
     │    "duration_s": 10  │  ATK_PPS=100             │  pps = env or 100
     │    "pps": 100        │                          │
     │    ...               │  PKTGEN_RATE=50          │  rate = env or 50
     │  }                   │                          │
     │  "pktgen": {         │                          │
     │    "rate": 50        │                          │
     │    "duration_ms":10000│                         │
     │  }                   │                          │
     └──────────────────────┘                          ┘
```

## PingMonitor (Singleton with Dual Backend)

`get_ping_monitor()` returns the singleton; never instantiate directly. `main.py`'s `finally` block ensures cleanup.

**fping -Q** (default on Linux/macOS when `fping` is on PATH):
- Sends 10 probes/second (`-p 100`), emits a summary line every 1 second (`-Q 1`)
- Summary format: `IP : xmt/rcv/%loss = 10/8/20%, min/avg/max = 2.1/5.7/12.3`
- Each summary becomes one `MonitorSample` with weighted `sent`/`received` counts
- Much higher temporal resolution than system ping

**System ping** (Windows fallback, or when `fping` not found):
- `ping -t` (Windows) or `ping -i` (Unix) continuous mode
- Parses per-reply RTT, detects loss via timeout/unreachable patterns
- Cross-locale loss detection (English + Chinese Windows messages)

Tools auto-collect `rtt_during` during attack via `get_samples_since(t0)` → `build_rtt_observation()`.

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

- `ChatOpenAI` → `https://api.deepseek.com`, model from `LLM_MODEL` env (default `deepseek-chat`). Instantiated in `graph.py` with `temperature=0.7`, `reasoning_effort="high"`, and `extra_body={"thinking": {"type": "enabled"}}`.
- `reasoning_content` monkey-patch in `graph.py` preserves DeepSeek's thinking across multi-turn. Without it, `deepseek-v4-pro` returns 400 on turn 2+ because the API requires `reasoning_content` to be echoed back.
- `src/llm/` (`client.py` `LLMClient`, `example.py`) is a standalone DeepSeek wrapper and a direct `deepseek-v4-pro` reasoning/thinking demo — it is NOT part of the agent loop, which uses `graph.py` → `ChatOpenAI`. Ignore it when tracing the runtime LLM path.
- API key from `DEEPSEEK_API_KEY` or `OPENAI_API_KEY` in `.env` (gitignored, use `.env_example` as template).

### Important Constraints

- **Cross-platform**: detect via `sys.platform`, never hardcode OS-specific flags (see `docs/debugging/cross_platform.md`).
- **Import order**: Pktgen config uses functions (`is_dry_run()`, `get_pktgen_host()`) not module constants, because `main()` sets env vars AFTER imports are resolved.
- **Vendored Pktgen code** (`pktgen_agent/`, `dsl/`, `topology.yaml`) is at project root and kept in sync with the Lua project. Project root must be on `sys.path`.
- **`pyyaml`** is a core dependency (not transitive) — required by vendored compiler.
- **Tool docstrings are stale**: the `@tool` docstrings in `tools.py` say max pps=200, max duration=10s, max packet_size=512, max flow_count=50 — the actual limits (in `traffic_send_tool.py` constants) are higher: pps=20000, duration=20s, packet_size=1024, flow_count=100. The system prompt template has the correct values; the docstrings should be updated to match.
- **RTT observation alignment**: `build_rtt_observation()` adds `attack_window` (start/end timestamps + mode), `observation_window` (first/last sample timestamps + `covers_attack_window` boolean), and `rtt_during` (per-sample RTT + aggregate stats). The LLM is instructed to check `covers_attack_window` before trusting any RTT measurement.
