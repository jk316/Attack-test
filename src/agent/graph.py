"""Agent builder using langchain.agents.create_agent for the closed-loop experiment."""
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
from src.tools.traffic_send_tool import (
    MAX_PPS, MAX_DURATION_S, MAX_PACKET_SIZE, MAX_FLOW_COUNT, MAX_IAT_JITTER_MS,
)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


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


def _build_system_prompt() -> str:
    """Render the system prompt from Jinja2 template."""
    env = Environment(loader=FileSystemLoader(str(_PROMPTS_DIR)))
    template = env.get_template("system_prompt.j2")
    return template.render(
        max_pps=MAX_PPS,
        max_duration_s=MAX_DURATION_S,
        max_packet_size=MAX_PACKET_SIZE,
        max_flow_count=MAX_FLOW_COUNT,
        max_iat_jitter_ms=MAX_IAT_JITTER_MS,
    )


def build_graph() -> CompiledStateGraph:
    """Build the closed-loop experiment agent using create_agent.

    Returns a CompiledStateGraph that follows the ReAct pattern:
    LLM reasons → calls tools → observes results → repeats until stop.

    The traffic_send tool is wrapped with a HITL gate via langgraph interrupt().
    Caller must handle resume via Command(resume=True/False).
    """
    model = _build_model()
    system_prompt = _build_system_prompt()

    return create_agent(
        model=model,
        tools=EXPERIMENT_TOOLS,
        system_prompt=system_prompt,
        checkpointer=MemorySaver(),
    )
