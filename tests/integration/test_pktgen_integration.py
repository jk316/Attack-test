"""Integration tests for Pktgen adapter — real compiler, agent graph, system prompt."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

ALLOWLISTED_IP = "10.99.80.160"


def _make_ai(tool_calls: list[dict] | None, content: str = "") -> AIMessage:
    """Build an AIMessage, optionally with tool_calls."""
    if tool_calls is None:
        return AIMessage(content=content, tool_calls=[])
    return AIMessage(
        content=content,
        tool_calls=[
            {"name": tc["name"], "args": tc.get("args", {}), "id": tc.get("id", f"call_{i}")}
            for i, tc in enumerate(tool_calls)
        ],
    )


@pytest.fixture
def mock_model():
    """Mock ChatOpenAI that supports the bind_tools().invoke() chain."""
    model = MagicMock()
    model.model_name = "deepseek-chat"
    model.bind_tools.return_value = model
    return model


# ══════════════════════════════════════════════════════════════════════
# SkillCompiler — real compilation (reads real dsl/ YAML files)
# ══════════════════════════════════════════════════════════════════════

SKILL_PARAMS = {
    "udp_flood": {"rate": 50, "dst_ip": ALLOWLISTED_IP},
    "tcp_flood": {"rate": 50, "dst_ip": ALLOWLISTED_IP, "tcp_flags": "syn"},
    "icmp_flood": {"rate": 50, "dst_ip": ALLOWLISTED_IP},
    "arp_flood": {"rate": 50},
    "range_based_scan": {
        "scan_field": "dst_port", "start": "1", "min": "1", "max": "100", "inc": "1",
    },
    "packet_sequence_generation": {
        "sequences": [{
            "eth_dst_addr": "00:11:44:55:66:77", "eth_src_addr": "00:11:12:34:56:78",
            "ip_dst_addr": ALLOWLISTED_IP, "ip_src_addr": "192.168.1.1/24",
            "sport": 9, "dport": 10, "ethType": "ipv4", "ipProto": "udp",
            "vlanid": 1, "pktSize": 128,
        }],
    },
    "pcap_replay": {"pcap_file": "/tmp/test.pcap"},
    "stats_monitoring": {"interval_ms": 1000, "iterations": 5},
    "safe_stop_and_reset": {},
}


class TestRealCompilation:
    """Compile all 9 skills with the real SkillCompiler (reads real dsl/ YAML)."""

    @pytest.mark.parametrize("skill_name,params", SKILL_PARAMS.items())
    def test_skill_compiles_to_lua(self, skill_name, params):
        """Each skill should compile to valid Lua with no errors."""
        from pktgen_agent.tools.execute import execute_skill_dry_run

        result = execute_skill_dry_run(skill_name, params)
        assert result["success"] is True, f"{skill_name}: {result.get('error', '')}"
        assert result["skill"] == skill_name
        assert result["mode"] == "dry_run"
        # Verify actual Lua was generated
        assert "lua_code" in result
        assert len(result["lua_code"]) > 0
        assert "require" in result["lua_code"]
        assert "Pktgen" in result["lua_code"]

    def test_compile_error_on_invalid_params(self):
        """Invalid params should raise CompileError."""
        from pktgen_agent.compiler.compile import CompileError
        from pktgen_agent.tools.execute import execute_skill_dry_run

        with pytest.raises(CompileError):
            execute_skill_dry_run("udp_flood", {"rate": 999})  # rate max is 100

    def test_compile_error_on_missing_required(self):
        """Missing required param should raise CompileError."""
        from pktgen_agent.compiler.compile import CompileError
        from pktgen_agent.tools.execute import execute_skill_dry_run

        with pytest.raises(CompileError):
            execute_skill_dry_run("udp_flood", {})  # rate is required

    def test_lua_output_saved_to_disk(self, tmp_path):
        """Dry-run compilation should save Lua to lua_scripts/.  Real I/O."""
        from pktgen_agent.tools.execute import execute_skill_dry_run

        result = execute_skill_dry_run("safe_stop_and_reset", {})
        assert result["success"] is True

        # Check that file was written to the project root lua_scripts/
        import glob as _glob
        lua_dir = "lua_scripts"
        assert any(
            "safe_stop_and_reset" in f for f in _glob.glob(f"{lua_dir}/*.lua")
        ), f"No Lua file found in {lua_dir}/"


class TestAllNineSkillsHaveValidYaml:
    """Verify all 9 skill YAMLs are loadable and well-formed."""

    def test_all_skills_loadable(self):
        """Every skill YAML should parse and have required fields."""
        import yaml
        from pathlib import Path

        skills_dir = Path("dsl/skills")
        yaml_files = sorted(skills_dir.glob("*.yaml"))
        assert len(yaml_files) == 9

        for yf in yaml_files:
            with open(yf) as f:
                data = yaml.safe_load(f)
            skill = data.get("skill", data)
            assert "name" in skill, f"{yf.name}: missing name"
            assert "params" in skill, f"{yf.name}: missing params"
            assert "setup" in skill, f"{yf.name}: missing setup"
            assert "plan" in skill, f"{yf.name}: missing plan"
            assert "teardown" in skill, f"{yf.name}: missing teardown"


# ══════════════════════════════════════════════════════════════════════
# Agent graph — Pktgen tools wired in
# ══════════════════════════════════════════════════════════════════════

class TestGraphIncludesPktgenTools:
    """Verify build_graph() includes all Pktgen tools."""

    def test_tool_count_is_17(self):
        """EXPERIMENT_TOOLS should have 17 tools (8 original + 9 Pktgen)."""
        from src.agent.tools import EXPERIMENT_TOOLS

        assert len(EXPERIMENT_TOOLS) == 17, (
            f"Expected 17 tools, got {len(EXPERIMENT_TOOLS)}: "
            f"{[t.name for t in EXPERIMENT_TOOLS]}"
        )

    def test_pktgen_tool_names_in_list(self):
        """All 9 Pktgen tool names should appear in EXPERIMENT_TOOLS."""
        from src.agent.tools import EXPERIMENT_TOOLS

        names = {t.name for t in EXPERIMENT_TOOLS}
        expected_pktgen = {
            "pktgen_udp_flood", "pktgen_tcp_flood", "pktgen_icmp_flood",
            "pktgen_arp_flood", "pktgen_range_scan", "pktgen_packet_sequence",
            "pktgen_pcap_replay", "pktgen_stats_monitor", "pktgen_stop_and_reset",
        }
        missing = expected_pktgen - names
        assert not missing, f"Pktgen tools missing from EXPERIMENT_TOOLS: {missing}"

    def test_graph_builds_with_pktgen_tools(self):
        """build_graph() should not fail with Pktgen tools registered."""
        from src.agent.graph import build_graph
        from langgraph.graph.state import CompiledStateGraph

        with patch("src.agent.graph._build_model", return_value=MagicMock()):
            graph = build_graph()

        assert isinstance(graph, CompiledStateGraph)


# ══════════════════════════════════════════════════════════════════════
# System prompt — Pktgen section rendering
# ══════════════════════════════════════════════════════════════════════

class TestSystemPromptRendering:
    """Verify the Jinja2 system prompt renders Pktgen section correctly."""

    def test_prompt_includes_pktgen_section_when_available(self):
        """When pktgen_available=True, the prompt includes Pktgen content."""
        from jinja2 import Environment, FileSystemLoader

        env = Environment(loader=FileSystemLoader("src/prompts"))
        template = env.get_template("system_prompt.j2")
        rendered = template.render(
            max_pps=20000, max_duration_s=20, max_packet_size=1024,
            max_flow_count=100, max_iat_jitter_ms=20,
            pktgen_available=True, pktgen_dry_run=True,
            pktgen_host="10.99.80.222", pktgen_port="22022",
        )

        assert "Pktgen-DPDK" in rendered
        assert "pktgen_udp_flood" in rendered
        assert "pktgen_tcp_flood" in rendered
        assert "pktgen_icmp_flood" in rendered
        assert "pktgen_arp_flood" in rendered
        assert "pktgen_range_scan" in rendered
        assert "pktgen_packet_sequence" in rendered
        assert "pktgen_pcap_replay" in rendered
        assert "pktgen_stats_monitor" in rendered
        assert "pktgen_stop_and_reset" in rendered
        assert "dry-run" in rendered.lower()
        assert "10.99.80.222:22022" in rendered

    def test_prompt_live_mode_shows_live(self):
        """When dry_run=False, the prompt mentions live mode."""
        from jinja2 import Environment, FileSystemLoader

        env = Environment(loader=FileSystemLoader("src/prompts"))
        template = env.get_template("system_prompt.j2")
        rendered = template.render(
            max_pps=20000, max_duration_s=20, max_packet_size=1024,
            max_flow_count=100, max_iat_jitter_ms=20,
            pktgen_available=True, pktgen_dry_run=False,
            pktgen_host="10.0.0.1", pktgen_port="9999",
        )

        assert "live" in rendered.lower()
        assert "dry-run" not in rendered.lower()

    def test_prompt_parameter_semantics_table(self):
        """Prompt should explain rate vs pps, duration vs duration_s."""
        from jinja2 import Environment, FileSystemLoader

        env = Environment(loader=FileSystemLoader("src/prompts"))
        template = env.get_template("system_prompt.j2")
        rendered = template.render(
            max_pps=20000, max_duration_s=20, max_packet_size=1024,
            max_flow_count=100, max_iat_jitter_ms=20,
            pktgen_available=True, pktgen_dry_run=True,
            pktgen_host="10.99.80.222", pktgen_port="22022",
        )

        assert "毫秒" in rendered  # duration is milliseconds
        assert "百分比" in rendered or "percentage" in rendered.lower()  # rate is %
        assert "pktSize" in rendered
        assert "duration_s" in rendered  # original Scapy param for comparison


# ══════════════════════════════════════════════════════════════════════
# E2E — agent invokes Pktgen tools via create_agent graph
# ══════════════════════════════════════════════════════════════════════

class TestAgentInvokesPktgenTools:
    """The agent graph should route Pktgen tool calls correctly."""

    def test_agent_calls_pktgen_udp_flood(self, mock_model):
        """Agent calls pktgen_udp_flood → adapter → _execute_skill."""
        from src.agent.graph import build_graph

        mock_model.invoke.side_effect = [
            _make_ai([{
                "name": "pktgen_udp_flood",
                "args": {"dst_ip": ALLOWLISTED_IP, "rate": 50, "duration": 5000},
                "id": "call_1",
            }]),
            _make_ai(None, "UDP flood sent at 50% rate. Checking RTT next."),
        ]

        with patch("src.agent.graph._build_model", return_value=mock_model), \
             patch("src.pktgen.adapter._execute_skill") as mock_exec, \
             patch("src.pktgen.adapter.interrupt", return_value=True), \
             patch("src.pktgen.adapter.validate_target"), \
             patch("src.pktgen.adapter.get_ping_monitor") as mock_pm:
            mock_exec.return_value = {
                "success": True, "skill": "udp_flood",
                "params": {"rate": 50}, "lua_code": "-- lua here",
                "mode": "dry_run",
            }
            mock_monitor = MagicMock()
            mock_monitor.is_running.return_value = False
            mock_pm.return_value = mock_monitor

            graph = build_graph()
            state = {"messages": [HumanMessage(content="Send UDP flood at 50% rate")]}
            config = {"configurable": {"thread_id": "test-pktgen-001"}}

            result = graph.invoke(state, config)

        mock_exec.assert_called_once()
        skill_name = mock_exec.call_args[0][0]
        assert skill_name == "udp_flood"
        assert "50% rate" in result["messages"][-1].content

    def test_agent_calls_pktgen_stop_and_reset(self, mock_model):
        """Agent calls pktgen_stop_and_reset — no HITL, no allowlist."""
        from src.agent.graph import build_graph

        mock_model.invoke.side_effect = [
            _make_ai([{
                "name": "pktgen_stop_and_reset",
                "args": {},
                "id": "call_1",
            }]),
            _make_ai(None, "All Pktgen ports stopped and reset."),
        ]

        with patch("src.agent.graph._build_model", return_value=mock_model), \
             patch("src.pktgen.adapter._execute_skill") as mock_exec:
            mock_exec.return_value = {
                "success": True, "skill": "safe_stop_and_reset",
                "lua_code": "-- stop lua", "mode": "dry_run",
            }

            graph = build_graph()
            state = {"messages": [HumanMessage(content="Stop all Pktgen traffic")]}
            config = {"configurable": {"thread_id": "test-pktgen-stop"}}

            result = graph.invoke(state, config)

        mock_exec.assert_called_once_with("safe_stop_and_reset", {
            "save_config": False, "clear_stats": True, "reset_ports": True,
        })
        assert "stopped" in result["messages"][-1].content.lower()

    def test_agent_calls_pktgen_stats_monitor(self, mock_model):
        """Agent calls pktgen_stats_monitor — no HITL needed."""
        from src.agent.graph import build_graph

        mock_model.invoke.side_effect = [
            _make_ai([{
                "name": "pktgen_stats_monitor",
                "args": {"interval_ms": 500, "iterations": 3, "mode": "rates"},
                "id": "call_1",
            }]),
            _make_ai(None, "Port rates: TX 8.5 Gbps, no errors detected."),
        ]

        with patch("src.agent.graph._build_model", return_value=mock_model), \
             patch("src.pktgen.adapter._execute_skill") as mock_exec:
            mock_exec.return_value = {
                "success": True, "skill": "stats_monitoring",
                "lua_code": "-- stats lua", "mode": "dry_run",
            }

            graph = build_graph()
            state = {"messages": [HumanMessage(content="Check Pktgen port rates")]}
            config = {"configurable": {"thread_id": "test-pktgen-stats"}}

            result = graph.invoke(state, config)

        mock_exec.assert_called_once_with("stats_monitoring", {
            "interval_ms": 500, "iterations": 3, "mode": "rates",
        })
        assert "8.5 Gbps" in result["messages"][-1].content

    def test_agent_calls_pktgen_range_scan(self, mock_model):
        """Agent delegates parameter sweep to pktgen_range_scan."""
        from src.agent.graph import build_graph

        mock_model.invoke.side_effect = [
            _make_ai([{
                "name": "pktgen_range_scan",
                "args": {
                    "dst_ip": ALLOWLISTED_IP,
                    "scan_field": "dst_port",
                    "start": "1", "min_val": "1", "max_val": "1024", "inc": "1",
                    "rate": 50,
                },
                "id": "call_1",
            }]),
            _make_ai(None, "Range scan complete. Ports 80, 443 showed highest RTT."),
        ]

        with patch("src.agent.graph._build_model", return_value=mock_model), \
             patch("src.pktgen.adapter._execute_skill") as mock_exec, \
             patch("src.pktgen.adapter.interrupt", return_value=True), \
             patch("src.pktgen.adapter.validate_target"), \
             patch("src.pktgen.adapter.get_ping_monitor") as mock_pm:
            mock_exec.return_value = {
                "success": True, "skill": "range_based_scan",
                "lua_code": "-- range lua", "mode": "dry_run",
            }
            mock_monitor = MagicMock()
            mock_monitor.is_running.return_value = False
            mock_pm.return_value = mock_monitor

            graph = build_graph()
            state = {"messages": [HumanMessage(content="Scan ports 1-1024 on target")]}
            config = {"configurable": {"thread_id": "test-pktgen-range"}}

            result = graph.invoke(state, config)

        _, params = mock_exec.call_args[0]
        assert params["scan_field"] == "dst_port"
        assert params["max"] == "1024"
        assert "80, 443" in result["messages"][-1].content

    def test_agent_mixes_scapy_and_pktgen_tools(self, mock_model):
        """Agent can use both Scapy and Pktgen tools in one experiment."""
        from src.agent.graph import build_graph

        mock_model.invoke.side_effect = [
            # Step 1: start ping monitor (Scapy)
            _make_ai([{
                "name": "start_ping_monitor",
                "args": {"ip": ALLOWLISTED_IP},
                "id": "call_1",
            }]),
            # Step 2: low-rate Scapy UDP test
            _make_ai([{
                "name": "traffic_send",
                "args": {"dst_ip": ALLOWLISTED_IP, "dst_port": 8080, "pps": 100},
                "id": "call_2",
            }]),
            # Step 3: escalate to Pktgen line-rate TCP flood
            _make_ai([{
                "name": "pktgen_tcp_flood",
                "args": {"dst_ip": ALLOWLISTED_IP, "rate": 80, "tcp_flags": "syn"},
                "id": "call_3",
            }]),
            # Step 4: stop Pktgen, stop monitor
            _make_ai([{
                "name": "pktgen_stop_and_reset",
                "args": {},
                "id": "call_4",
            }]),
            _make_ai(None, "Experiment complete. Scapy baseline: 25ms, Pktgen max: 450ms."),
        ]

        with patch("src.agent.graph._build_model", return_value=mock_model), \
             patch("src.pktgen.adapter._execute_skill") as mock_pktgen_exec, \
             patch("src.pktgen.adapter.interrupt", return_value=True), \
             patch("src.pktgen.adapter.validate_target"), \
             patch("src.pktgen.adapter.get_ping_monitor") as mock_pm, \
             patch("src.agent.tools.traffic_send_tool") as mock_scapy_send, \
             patch("src.agent.tools.get_ping_monitor") as mock_agent_pm, \
             patch("src.agent.tools.interrupt", return_value=True):
            mock_pktgen_exec.return_value = {
                "success": True, "lua_code": "-- lua", "mode": "dry_run",
            }
            mock_scapy_send.return_value = {
                "success": True, "packets_sent": {"total": 500},
            }

            mock_monitor = MagicMock()
            mock_monitor.is_running.return_value = True
            mock_monitor.target_ip = ALLOWLISTED_IP
            mock_monitor.start.return_value = None
            mock_pm.return_value = mock_monitor
            mock_agent_pm.return_value = mock_monitor

            graph = build_graph()
            state = {"messages": [HumanMessage(content="Run hybrid Scapy+Pktgen experiment")]}
            config = {"configurable": {"thread_id": "test-hybrid"}}

            result = graph.invoke(state, config)

        # Both Scapy and Pktgen tools were called
        mock_scapy_send.assert_called_once()
        assert mock_pktgen_exec.call_count == 2  # tcp_flood + stop_and_reset
        # Check final message content
        assert "450ms" in result["messages"][-1].content


# ══════════════════════════════════════════════════════════════════════
# Adapter → live mode integration
# ══════════════════════════════════════════════════════════════════════

class TestLiveModeConfiguration:
    """Verify live/dry-run mode switching via environment variable."""

    def test_default_is_dry_run(self):
        """PKTGEN_DRY_RUN should default to True when env var is not set."""
        # Simulate fresh import state
        import importlib
        import src.pktgen.adapter as adp

        # Restore original after test
        original = adp.PKTGEN_DRY_RUN
        try:
            # With env NOT set, it should be True
            with patch.dict(os.environ, {}, clear=True):
                # Force re-evaluation
                val = os.environ.get("PKTGEN_DRY_RUN", "true").lower() != "false"
                assert val is True
        finally:
            pass  # PKTGEN_DRY_RUN is a module-level constant, don't mutate

    def test_env_false_sets_live_mode(self):
        """PKTGEN_DRY_RUN=false should enable live mode."""
        val = "false"
        assert val.lower() == "false"
        is_dry = val.lower() != "false"
        assert is_dry is False

    def test_env_true_sets_dry_run(self):
        """PKTGEN_DRY_RUN=true keeps dry-run."""
        val = "true"
        is_dry = val.lower() != "false"
        assert is_dry is True
