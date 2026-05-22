"""Agent builder using langchain.agents.create_agent for the closed-loop experiment."""
import os

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.state import CompiledStateGraph

from src.agent.tools import EXPERIMENT_TOOLS
from src.agent.system_prompt import build_system_prompt


def _build_model() -> ChatOpenAI:
    """Create ChatOpenAI instance configured for DeepSeek API."""
    api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "DEEPSEEK_API_KEY or OPENAI_API_KEY environment variable not set"
        )
    model_name = os.environ.get("LLM_MODEL", "deepseek-chat")
    return ChatOpenAI(
        model=model_name,
        base_url="https://api.deepseek.com",
        api_key=api_key,
        temperature=0.7,
    )


def build_graph() -> CompiledStateGraph:
    """Build the closed-loop experiment agent using create_agent.

    Returns a CompiledStateGraph that follows the ReAct pattern:
    LLM reasons → calls tools → observes results → repeats until stop.

    The traffic_send tool is wrapped with a HITL gate via langgraph interrupt().
    Caller must handle resume via Command(resume=True/False).
    """
    model = _build_model()
    system_prompt = build_system_prompt()

    return create_agent(
        model=model,
        tools=EXPERIMENT_TOOLS,
        system_prompt=system_prompt,
        checkpointer=MemorySaver(),
    )
