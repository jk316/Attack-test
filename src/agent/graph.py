"""Agent builder using langchain.agents.create_agent for the closed-loop experiment."""
import importlib.util
import os
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from langchain.agents import create_agent
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.state import CompiledStateGraph
from dotenv import load_dotenv

from src.agent.tools import EXPERIMENT_TOOLS
from src.pktgen.adapter import get_pktgen_host, get_pktgen_port, is_dry_run
from src.trex.config import get_trex_host, get_trex_port, is_trex_dry_run
from src.trex.tools import TREX_TOOLS
from src.tools.traffic_send_tool import (
    MAX_PPS, MAX_DURATION_S, MAX_PACKET_SIZE, MAX_FLOW_COUNT, MAX_IAT_JITTER_MS,
)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def _pktgen_available() -> bool:
    """Check whether Pktgen tools are actually available (vendored code + YAMLs)."""
    try:
        from pktgen_agent.tools.execute import execute_skill_dry_run
        return True
    except ImportError:
        return False


def _trex_available() -> bool:
    """Whether the TRex client lib is importable on this host.

    Uses find_spec (not import) so TRex's bundled scapy is never pulled into the
    agent process, avoiding a clash with the project's scapy 2.7.0. The
    write/run tools themselves are always registered; this only gates whether
    the prompt describes them.
    """
    return importlib.util.find_spec("trex_stl_lib") is not None


def _patch_reasoning_content():
    """Monkey-patch ChatOpenAI to preserve DeepSeek reasoning_content across turns.

    ChatOpenAI uses two module-level functions that both drop reasoning_content:
    1. _convert_dict_to_message — API response → AIMessage (inbound)
    2. _convert_message_to_dict — AIMessage → API request dict (outbound)

    Without these patches, deepseek-v4-pro returns a 400 error on the second
    turn because the API requires reasoning_content to be echoed back.
    """
    import langchain_openai.chat_models.base as base

    # ── Inbound: extract reasoning_content from API response ──────────
    _orig_dict_to_msg = base._convert_dict_to_message

    def _patched_dict_to_msg(_dict):
        msg = _orig_dict_to_msg(_dict)
        if isinstance(msg, AIMessage) and "reasoning_content" in _dict:
            msg.additional_kwargs["reasoning_content"] = _dict["reasoning_content"]
        return msg

    base._convert_dict_to_message = _patched_dict_to_msg

    # ── Outbound: include reasoning_content in API request ────────────
    _orig_msg_to_dict = base._convert_message_to_dict

    def _patched_msg_to_dict(message, api="chat/completions"):
        result = _orig_msg_to_dict(message, api)
        if isinstance(message, AIMessage) and "reasoning_content" in message.additional_kwargs:
            result["reasoning_content"] = message.additional_kwargs["reasoning_content"]
        return result

    base._convert_message_to_dict = _patched_msg_to_dict


load_dotenv()
_patch_reasoning_content()


def _build_model() -> ChatOpenAI:
    """Create ChatOpenAI instance configured for DeepSeek API."""
    api_key = (os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError(
            "DEEPSEEK_API_KEY or OPENAI_API_KEY environment variable not set"
        )
    model_name = os.environ.get("LLM_MODEL", "deepseek-chat").strip()
    return ChatOpenAI(
        model=model_name,
        base_url="https://api.deepseek.com",
        api_key=api_key,
        temperature=0.7,
        reasoning_effort="high",
        extra_body={"thinking": {"type": "enabled"}},
    )


def _build_system_prompt(max_iters: int = 20, no_improve_limit: int = 5, mode: str = "experiment") -> str:
    """Render the system prompt from the Jinja2 template for the given mode.

    mode="catalog" uses the TRex attack catalog exploration template; anything
    else uses the default closed-loop experiment template.
    """
    env = Environment(loader=FileSystemLoader(str(_PROMPTS_DIR)))
    template_name = "trex_catalog_prompt.j2" if mode == "catalog" else "system_prompt.j2"
    template = env.get_template(template_name)
    return template.render(
        max_pps=MAX_PPS,
        max_duration_s=MAX_DURATION_S,
        max_packet_size=MAX_PACKET_SIZE,
        max_flow_count=MAX_FLOW_COUNT,
        max_iat_jitter_ms=MAX_IAT_JITTER_MS,
        max_iters=max_iters,
        no_improve_limit=no_improve_limit,
        # Scapy defaults (from env / experiment.json / CLI)
        atk_duration_s=int(os.environ.get("ATK_DURATION_S", "10")),
        atk_pps=int(os.environ.get("ATK_PPS", "100")),
        atk_packet_size=int(os.environ.get("ATK_PACKET_SIZE", "64")),
        atk_flow_count=int(os.environ.get("ATK_FLOW_COUNT", "1")),
        # Pktgen defaults (from env / experiment.json / CLI)
        pktgen_rate=os.environ.get("PKTGEN_RATE", "50"),
        pktgen_duration_ms=os.environ.get("PKTGEN_DURATION_MS", "10000"),
        # Pktgen-DPDK context
        pktgen_available=_pktgen_available(),
        pktgen_dry_run=is_dry_run(),
        pktgen_host=get_pktgen_host(),
        pktgen_port=str(get_pktgen_port()),
        # TRex client context
        trex_available=_trex_available(),
        trex_dry_run=True if mode == "catalog" else is_trex_dry_run(),
        trex_host=get_trex_host(),
        trex_port=str(get_trex_port()),
        # TRex attack catalog exploration (mode="catalog")
        catalog_target=int(os.environ.get("CATALOG_TARGET", "10")),
        explore_direction=os.environ.get("EXPLORE_DIRECTION", ""),
    )


def build_graph(
    max_iters: int = 20, no_improve_limit: int = 5, mode: str = "experiment",
) -> CompiledStateGraph:
    """Build the agent using create_agent.

    Args:
        max_iters: Maximum iterations (injected into system prompt).
        no_improve_limit: Stop after N rounds without improvement
            (closed-loop experiment mode only).
        mode: "experiment" (default closed-loop RTT experiment) or "catalog"
            (TRex attack catalog exploration — TRex tools only, forced
            dry-run, no traffic, no HITL interrupts).

    Returns a CompiledStateGraph that follows the ReAct pattern:
    LLM reasons → calls tools → observes results → repeats until stop.

    The traffic tools are wrapped with HITL gates via langgraph interrupt().
    Caller must handle resume via Command(resume=True/False).
    """
    model = _build_model()
    system_prompt = _build_system_prompt(
        max_iters=max_iters, no_improve_limit=no_improve_limit, mode=mode,
    )

    # Catalog mode: only the 2 TRex code tools (write + dry-run check) are
    # registered — structurally guarantees no traffic tool is callable.
    tools = TREX_TOOLS if mode == "catalog" else EXPERIMENT_TOOLS

    # NOTE: the graph's superstep budget (recursion_limit) is passed by the
    # caller via the invoke config — see _recursion_limit() in main.py.
    return create_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        checkpointer=MemorySaver(),
    )
