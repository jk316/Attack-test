# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Closed-Loop Network Experiment Agent — a LangChain ReAct agent that autonomously explores traffic parameters to maximize ping RTT, operating under strict safety constraints (allowlist, rate limits, HITL approval). Built with Python 3.11+, Scapy, LangChain, and DeepSeek API.

## Commands

```bash
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

# Run the agent (requires DEEPSEEK_API_KEY or OPENAI_API_KEY)
uv run python src/main.py --target-ip 10.99.80.160 --max-iters 5

# Run with PCAP baseline profiling
uv run python src/main.py --target-ip 10.99.80.160 --pcap-path data/sample.pcapng --max-iters 5
```

## Architecture

The agent uses `langchain.agents.create_agent` with the ReAct pattern:

```
LLM reasons → calls tools → observes results → repeats until stop
```

### Key Files

| File | Role |
|------|------|
| `src/agent/graph.py` | Builds the agent via `create_agent()`, model config, system prompt rendering, DeepSeek reasoning_content monkey-patch |
| `src/agent/tools.py` | Wraps tool functions as `@tool`-decorated LangChain tools; `traffic_send` includes HITL gate via `interrupt()` |
| `src/agent/state.py` | `AgentState` TypedDict + helpers (`compute_reward`, `check_stop_condition`, `update_best`) |
| `src/llm/client.py` | DeepSeek API client wrapper (OpenAI-compatible) with JSON response parsing |
| `src/prompts/system_prompt.j2` | Jinja2 system prompt template with parameter bounds and optimization strategy |
| `src/main.py` | CLI entry point — parses args, runs agent loop with HITL polling |

### Agent Tools

| Tool | Underlying Function | HITL? |
|------|-------------------|-------|
| `pcap_profile` | `src/tools/pcap_profile_tool.py` | No |
| `traffic_send` | `src/tools/traffic_send_tool.py` | Yes (`interrupt()`) |
| `ping_rtt` | `src/tools/ping_rtt_tool.py` | No |
| `log_result` | `src/tools/log_tool.py` | No |

### Experiment Protocol (per iteration)

1. **Send Traffic** → `traffic_send` (HITL approval required)
2. **Measure RTT** → `ping_rtt`
3. **Log Result** → `log_result`
4. **Analyze & Decide** → LLM decides next params or stop

## Key Conventions

### TDD Workflow
Every feature follows strict TDD: write tests first (RED) → implement (GREEN) → verify 80%+ coverage. Tests use `from src.tools.xxx import xxx` imports. `tests/conftest.py` adds the project root to `sys.path` so `src` is importable.

### Security Validation
All tools that target network destinations must enforce:
- **allowlist**: Only destinations in `src/config/allowlist.json` are permitted
- **No broadcast/multicast**: IP validation rejects `.255` and `224.0.0.0/4` ranges
- **No src_ip forgery**: tools must not accept `src_ip` parameter
- **Rate/duration limits**: hard-coded constants (MAX_PPS, MAX_DURATION_S, etc.)

Validation functions (`validate_target`, `is_broadcast`, `is_multicast`, `is_allowlisted`) live in `src/tools/ping_rtt_tool.py` and are imported by other tools.

### Tool Output Format
All tools return a plain `dict` (not a Pydantic model). Success responses include `"success": True`; errors raise `ValueError` for parameter violations and `ImportError` for missing dependencies.

### Allowlist
`src/config/allowlist.json` contains `{"hosts": ["10.99.80.160"]}`. Tests that need to pass allowlist validation must use `10.99.80.160` as the target IP. Tests that verify allowlist rejection use arbitrary non-list IPs like `192.168.1.99`.

### LLM / DeepSeek Integration
- Uses `langchain_openai.ChatOpenAI` pointed at `https://api.deepseek.com`
- Model controlled by `LLM_MODEL` env var (default `deepseek-chat`)
- API key from `DEEPSEEK_API_KEY` or `OPENAI_API_KEY` env var
- **reasoning_content monkey-patch** in `graph.py`: ChatOpenAI drops DeepSeek's `reasoning_content` field by default — the patch preserves it across inbound (API→AIMessage) and outbound (AIMessage→API) conversions to avoid 400 errors on multi-turn conversations

### Parameter Limits

| Parameter | Max | Constant |
|-----------|-----|----------|
| pps | 200 | `MAX_PPS` |
| duration_s | 10 | `MAX_DURATION_S` |
| packet_size | 512 | `MAX_PACKET_SIZE` |
| flow_count | 50 | `MAX_FLOW_COUNT` |
| iat_jitter_ms | 20 | `MAX_IAT_JITTER_MS` |
| max_iters | 20 | default in state |
| no_improve_limit | 5 | default in state |

## Important Engineering Constraints

- **All CLI tools must support Linux and Windows**: detect platform via `sys.platform`, never hardcode OS-specific commands or flags. See [docs/debugging/cross_platform.md](docs/debugging/cross_platform.md).
- **Always validate serialization compatibility**: mock-based tests do not catch type errors from real data (e.g. `Decimal` in JSON). See [docs/debugging/scapy_decimal.md](docs/debugging/scapy_decimal.md).
- **Prefer real-environment verification over mocks**: after implementing any tool that calls external commands, run it against a real target to confirm end-to-end correctness.

## Development Status

All 5 phases are complete. Tracked in `PROGRESS.md`. See `PLAN.md` for the full roadmap.
