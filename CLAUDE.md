# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Closed-Loop Network Experiment Agent — a LangChain ReAct agent that autonomously explores traffic parameters to maximize ping RTT, with continuous background ping monitoring, web console, and strict safety constraints (allowlist, rate limits, HITL approval). Built with Python 3.11+, Scapy, LangChain, FastAPI, and DeepSeek API.

## Commands

```bash
# ── Testing ──────────────────────────────────────────────────────
# Run all unit tests
uv run pytest tests/unit/ -v

# Run all integration tests
uv run pytest tests/integration/ -v

# Run all E2E tests
uv run pytest tests/e2e/ -v

# Run full test suite with coverage (80% minimum required)
uv run pytest --cov=src --cov-report=term-missing

# Run a single test file
uv run pytest tests/unit/test_traffic_send_tool.py -v

# ── CLI Agent ────────────────────────────────────────────────────
# Interactive mode (HITL prompts for each traffic send)
uv run python src/main.py --target-ip 10.99.80.160 --max-iters 5

# Auto-approve mode (bypass HITL prompts, for CI/automation)
uv run python src/main.py --target-ip 10.99.80.160 --max-iters 5 --auto-approve

# With PCAP baseline profiling
uv run python src/main.py --target-ip 10.99.80.160 --pcap-path data/sample.pcapng --max-iters 5

# ── Web Console ──────────────────────────────────────────────────
# Start the web server (FastAPI + WebSocket)
uv run uvicorn backend.server:app --host 0.0.0.0 --port 8000 --reload

# Then open http://localhost:8000 in browser
```

## Architecture

The agent uses `langchain.agents.create_agent` with the ReAct pattern:

```
LLM reasons → calls tools → observes results → repeats until stop
```

Two runtime modes exist:
1. **CLI mode** (`src/main.py`) — synchronous, `input()`-based HITL, runs via `graph.invoke()`
2. **Web mode** (`backend/server.py` + `backend/experiment.py`) — async FastAPI + WebSocket, async queue-based HITL, runs via `graph.ainvoke()`

### Key Files

| File | Role |
|------|------|
| `src/agent/graph.py` | Builds the agent via `create_agent()`, model config, system prompt rendering, DeepSeek reasoning_content monkey-patch |
| `src/agent/tools.py` | 8 `@tool`-decorated LangChain tools; `traffic_send`/`mixed_traffic_send` include HITL gate via `interrupt()`; traffic tools auto-collect RTT samples from PingMonitor |
| `src/agent/state.py` | `AgentState` TypedDict + helpers (`compute_reward`, `check_stop_condition`, `update_best`) |
| `src/main.py` | CLI entry point — parses args (incl. `--auto-approve`), runs agent loop with HITL polling, configures logging, ensures PingMonitor cleanup |
| `src/prompts/system_prompt.j2` | Jinja2 system prompt — continuous ping experiment protocol, RTT analysis strategy, mixed traffic schema |
| `src/tools/ping_monitor.py` | **PingMonitor** class — background `ping` subprocess + parser thread, thread-safe deque of `(ts, rtt_ms)` samples, `get_stats()` / `get_samples_since()` queries, module-level singleton `get_ping_monitor()` |
| `src/tools/traffic_send_tool.py` | UDP traffic sender with parameter clamps |
| `src/tools/mixed_traffic_tool.py` | Multi-protocol traffic (TCP/UDP/DNS/ICMP/Raw) via JSON spec; includes `validate_traffic_spec()` with injection scanning |
| `src/tools/ping_rtt_tool.py` | One-shot ping + security validators (`validate_target`, `is_allowlisted`, etc.) |
| `src/tools/pcap_profile_tool.py` | PCAP/PCAPng file analysis (ports, sizes, IAT stats, flow counts) |
| `src/tools/log_tool.py` | JSONL experiment logging |
| `backend/server.py` | FastAPI app: `GET /` (serves frontend), `WS /ws/{client_id}` (real-time experiment), REST endpoints for start/stop/status/upload |
| `backend/experiment.py` | `ExperimentManager` — async bridge between LangGraph agent and WebSocket; `asyncio.Queue` for HITL; pushes events (status, messages, tool_result, hitl_request) to clients |
| `frontend/index.html` | Web console UI — left panel: message stream; right sidebar: config form + stats panel; HITL modal |
| `frontend/app.js` | WebSocket client — connects with random ID, dispatches 6 message types, Promise-based approve/reject |
| `frontend/style.css` | Dark theme CSS with custom properties |
| `src/config/experiment.json` | Default experiment parameters |
| `src/config/allowlist.json` | Allowlisted target IPs: `10.99.80.160`, `100.1.11.4` |
| `src/llm/client.py` | Legacy `LLMClient` wrapper — NOT used by the agent (graph.py uses `ChatOpenAI` directly) |
| `src/llm/example.py` | Standalone DeepSeek tool-calling demo — NOT used by the main agent |
| `test.py` | Standalone LangGraph ReAct demo (different from main agent) — learning/reference file |

### Agent Tools (8 total)

| Tool | Underlying Function | HITL? | Purpose |
|------|-------------------|-------|---------|
| `pcap_profile` | `pcap_profile_tool` | No | Analyze PCAP for traffic characteristics |
| `start_ping_monitor` | `PingMonitor.start()` | No | Start background continuous ping |
| `read_ping_stats` | `PingMonitor.get_stats()` | No | Read current RTT statistics |
| `stop_ping_monitor` | `PingMonitor.stop()` | No | Stop background ping |
| `traffic_send` | `traffic_send_tool` | Yes | Send UDP traffic (HITL gate via `interrupt()`) |
| `mixed_traffic_send` | `mixed_traffic_send_tool` | Yes | Send multi-protocol traffic (TCP/UDP/DNS/ICMP/Raw) |
| `ping_rtt` | `ping_rtt_tool` | No | One-shot ping (fallback when monitor not active) |
| `log_result` | `log_tool` | No | Append result to JSONL log |

### PingMonitor Architecture

```
PingMonitor (singleton, src/tools/ping_monitor.py)
├── subprocess: ping -t <ip> (Windows) / ping -i <ip> (Linux)
├── reader thread: parses stdout line-by-line, extracts time=Xms
├── deque<(timestamp, rtt_ms)>: thread-safe, max 2000 samples
├── get_stats(window_s) → {avg, min, max, latest, sample_count}
├── get_samples_since(ts) → [{ts, rtt_ms}, ...]
└── shared via get_ping_monitor() → traffic_send tools auto-collect
    RTT during attack window, returning rtt_during in tool result
```

### Experiment Protocol (Continuous Ping)

```
Init:   pcap_profile (if PCAP provided) → start_ping_monitor
Loop:
  1. read_ping_stats    → baseline RTT before attack
  2. traffic_send       → attack (tool auto-collects RTT during attack,
                           returned as rtt_during field)
  3. read_ping_stats    → post-attack RTT recovery
  4. log_result         → persist this iteration
  5. analyze & decide   → adjust params, continue or stop
Cleanup: stop_ping_monitor
```

### Data Flow at Runtime

**CLI mode:**
```
main.py parses CLI args → loads experiment.json defaults
  → build_graph() renders system_prompt.j2 → creates agent with EXPERIMENT_TOOLS
  → invoke with user message → agent enters ReAct loop
  → on traffic_send/mixed_traffic_send: interrupt() pauses → HITL poll (input() or --auto-approve) → Command(resume=...) → continues
  → traffic tools query PingMonitor for rtt_during samples
  → agent stops when LLM returns no tool_calls
  → finally: PingMonitor.stop() cleanup
  → results: data/experiment.jsonl, logs: data/agent.log
```

**Web mode:**
```
browser → WS /ws/{id} → ExperimentManager.start()
  → graph.ainvoke() → hits interrupt() → pushes hitl_request to WS
  → user clicks approve/reject → WS hitl_response → asyncio.Queue → Command(resume=...)
  → tool results / messages pushed to WS as they happen
  → experiment_done pushed on completion
```

## Key Conventions

### TDD Workflow
Every feature follows strict TDD: write tests first (RED) → implement (GREEN) → verify 80%+ coverage. Tests use `from src.tools.xxx import xxx` imports. `tests/conftest.py` adds the project root to `sys.path` so `src` is importable.

### Security Validation
All tools that target network destinations must enforce:
- **allowlist**: Only destinations in `src/config/allowlist.json` are permitted
- **No broadcast/multicast**: IP validation rejects `.255` and `224.0.0.0/4` ranges
- **No src_ip forgery**: tools must not accept `src_ip` parameter
- **Rate/duration limits**: hard-coded constants (MAX_PPS, MAX_DURATION_S, etc.)
- **Injection scanning**: `mixed_traffic_tool` validates JSON specs for `__import__`, `eval(`, `os.system` patterns

Validation functions (`validate_target`, `is_broadcast`, `is_multicast`, `is_allowlisted`) live in `src/tools/ping_rtt_tool.py` and are imported by other tools.

### Tool Output Format
All tools return a plain `dict` (not a Pydantic model). Success responses include `"success": True`; errors raise `ValueError` for parameter violations and `ImportError` for missing dependencies.

### Test Target IPs
Tests that need to pass allowlist validation must use `10.99.80.160`. Tests that verify allowlist rejection use arbitrary non-list IPs like `192.168.1.99`.

### LLM / DeepSeek Integration
- Uses `langchain_openai.ChatOpenAI` pointed at `https://api.deepseek.com`
- Model controlled by `LLM_MODEL` env var (default `deepseek-chat`)
- API key from `DEEPSEEK_API_KEY` or `OPENAI_API_KEY` env var
- **reasoning_content monkey-patch** in `graph.py`: ChatOpenAI drops DeepSeek's `reasoning_content` field by default — the patch preserves it across inbound (API→AIMessage) and outbound (AIMessage→API) conversions to avoid 400 errors on multi-turn conversations
- Model config uses `reasoning_effort="high"` and `extra_body={"thinking": {"type": "enabled"}}` for DeepSeek's thinking mode

### Parameter Limits

| Parameter | Max | Constant |
|-----------|-----|----------|
| pps | 20000 | `MAX_PPS` |
| duration_s | 20 | `MAX_DURATION_S` |
| packet_size | 1024 | `MAX_PACKET_SIZE` |
| flow_count | 100 | `MAX_FLOW_COUNT` |
| iat_jitter_ms | 20 | `MAX_IAT_JITTER_MS` |
| max_iters | 20 | default in state |
| no_improve_limit | 5 | default in state |
| mixed streams | 10 | `MAX_STREAMS` in mixed_traffic_tool |

## Important Engineering Constraints

- **All CLI tools must support Linux and Windows**: detect platform via `sys.platform`, never hardcode OS-specific commands or flags. See `docs/debugging/cross_platform.md`.
- **Always validate serialization compatibility**: mock-based tests do not catch type errors from real data (e.g. `Decimal` in JSON). See `docs/debugging/scapy_decimal.md`.
- **Prefer real-environment verification over mocks**: after implementing any tool that calls external commands, run it against a real target to confirm end-to-end correctness.
- **PingMonitor is a singleton**: use `get_ping_monitor()` — never instantiate `PingMonitor()` directly in tools. The `finally` block in `main.py` ensures cleanup.
- **HITL works differently in CLI vs Web mode**: CLI uses `input()` with optional `--auto-approve`; Web mode uses `asyncio.Queue` with WebSocket messages.
- **`.env` is gitignored but present on disk**: use `.env_example` as template. Never commit real API keys.
