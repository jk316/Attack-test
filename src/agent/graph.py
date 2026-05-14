"""LangGraph StateGraph builder for the closed-loop experiment agent."""
from typing import Any

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.state import CompiledStateGraph

from src.agent.state import AgentState, check_stop_condition
from src.agent.nodes import plan_params, send_traffic, measure_rtt, log_result, update_state


def should_continue(state: dict[str, Any]) -> str:
    """Route to END if stop conditions are met, otherwise loop to plan_params."""
    iteration = state.get("iteration", 0)
    consecutive_no_improve = state.get("consecutive_no_improve", 0)
    max_iters = state.get("max_iters", 20)
    no_improve_limit = state.get("no_improve_limit", 5)

    if check_stop_condition(iteration, consecutive_no_improve, max_iters, no_improve_limit):
        return END
    return "plan_params"


def build_graph() -> CompiledStateGraph:
    """Build and compile the closed-loop experiment graph.

    Returns a CompiledStateGraph ready for invoke/stream with checkpointing.
    HITL: the send_traffic node calls langgraph interrupt() internally.
    """
    builder = StateGraph(AgentState)

    # ── Nodes ────────────────────────────────────────────────────
    builder.add_node("plan_params", plan_params)
    builder.add_node("send_traffic", send_traffic)
    builder.add_node("measure_rtt", measure_rtt)
    builder.add_node("log_result", log_result)
    builder.add_node("update_state", update_state)

    # ── Linear edges ─────────────────────────────────────────────
    builder.add_edge(START, "plan_params")
    builder.add_edge("plan_params", "send_traffic")
    builder.add_edge("send_traffic", "measure_rtt")
    builder.add_edge("measure_rtt", "log_result")
    builder.add_edge("log_result", "update_state")

    # ── Conditional loop-back ────────────────────────────────────
    builder.add_conditional_edges("update_state", should_continue)

    # ── Compile with checkpointing ───────────────────────────────
    return builder.compile(checkpointer=MemorySaver())
