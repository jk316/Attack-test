# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Closed-Loop Network Experiment Agent — a LangGraph agent that autonomously explores traffic parameters to maximize ping RTT, operating under strict safety constraints (allowlist, rate limits, HITL approval). Built with Python 3.11+ and Scapy.

## Commands

```bash
# Run all unit tests
uv run pytest tests/unit/ -v

# Run a single test file
uv run pytest tests/unit/test_traffic_send_tool.py -v

# Run with coverage (80% minimum required)
uv run pytest tests/unit/ --cov=src/tools --cov-report=term-missing

# Run a specific test
uv run pytest tests/unit/test_traffic_send_tool.py::TestTrafficSendTool::test_pps_exceeds_max_rejected -v
```

## Architecture

The agent follows a closed-loop pipeline:

```
Plan Action → Send Traffic → Measure RTT → Log Result → (loop)
```

Implemented in phases:
- **Phase 1 (Tools)**: Standalone Python functions that the agent will call. Each is a discrete operation with strict input validation.
- **Phase 2 (Agent)**: LangGraph state machine with ReAct tool-calling. Nodes handle param exploration, HITL approval, and reward optimization (`reward = avg_rtt_ms - penalty(loss_pct)`).
- **Phase 3 (Integration)**: E2E tests covering the full closed loop.

## Git Workflow

After completing each phase (e.g., a full tool implementation with tests passing and 80%+ coverage), you MUST:
1. Stage all changed files and create a commit following the PLAN.md checkpoint naming: `test: add <feature> tests (RED)` / `fix: implement <feature> (GREEN)`
2. Push to the remote repository: `git push origin main`

Do NOT skip committing after a phase is complete.

## Key Conventions

### TDD Workflow
Every tool follows strict TDD: write tests first (RED) → implement (GREEN) → verify 80%+ coverage. Tests use `from src.tools.xxx import xxx` imports. `tests/conftest.py` adds the project root to `sys.path` so `src` is importable.

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

## Important Engineering Constraints

- **All CLI tools must support Linux and Windows**: detect platform via `sys.platform`, never hardcode OS-specific commands or flags. See [docs/debugging/cross_platform.md](docs/debugging/cross_platform.md).
- **Always validate serialization compatibility**: mock-based tests do not catch type errors from real data (e.g. `Decimal` in JSON). See [docs/debugging/scapy_decimal.md](docs/debugging/scapy_decimal.md).
- **Prefer real-environment verification over mocks**: after implementing any tool that calls external commands, run it against a real target to confirm end-to-end correctness.

## Development Status

Tracked in `PROGRESS.md`. Currently Phase 1 is 3/4 done (ping_rtt_tool, pcap_profile_tool, traffic_send_tool complete; log_tool next). See `PLAN.md` for the full roadmap and parameter limits.
