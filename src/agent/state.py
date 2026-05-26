"""Agent state definition for the closed-loop network experiment agent."""
import operator
from typing import Annotated, TypedDict, Any

from langgraph.graph import add_messages


class AgentState(TypedDict, total=False):
    """Closed-loop network experiment agent state.

    Nodes return partial state updates. Non-Annotated fields are replaced;
    Annotated fields apply their reducer to merge old + new values.
    """
    # ── Iteration tracking ──────────────────────────────────────
    iteration: int
    """Current iteration number, 0-indexed."""

    # ── Accumulated history (reducer: operator.add) ─────────────
    rtt_history: Annotated[list[float], operator.add]
    """Per-iteration avg_rtt_ms values. Nodes return {rtt_history: [val]}."""

    # ── Optimization state ──────────────────────────────────────
    best_rtt: float
    """Best (highest) avg_rtt_ms observed so far, initialized to 0.0."""

    consecutive_no_improve: int
    """Counter: increments when reward does not exceed best."""

    reward: float
    """Current reward = avg_rtt_ms - penalty(loss_pct)."""

    # ── Configuration ───────────────────────────────────────────
    target_ip: str
    """Destination IP for traffic_send_tool and ping_rtt_tool."""

    pcap_path: str
    """Optional path to a PCAP file for baseline traffic profiling."""

    pcap_profile: dict[str, Any]
    """Results from pcap_profile_tool: IAT stats, flow counts, port histograms."""

    log_path: str
    """Path to the JSONL experiment log file."""

    max_iters: int
    """Maximum number of iterations before forced stop (default 20)."""

    no_improve_limit: int
    """Stop after this many consecutive rounds without RTT improvement (default 5)."""

    # ── ReAct conversation and tool-calling ─────────────────────
    messages: Annotated[list, add_messages]
    """LLM conversation history with tool call/result pairs."""


def compute_reward(avg_rtt_ms: float, loss_pct: float) -> float:
    """Compute reward = avg_rtt_ms - penalty(loss_pct).

    Penalty is loss_pct * 0.1. Returns 0.0 if avg_rtt_ms is inf (all loss).
    """
    if avg_rtt_ms == float('inf'):
        return 0.0
    return avg_rtt_ms - loss_pct * 0.1


def check_stop_condition(
    iteration: int,
    consecutive_no_improve: int,
    max_iters: int = 20,
    no_improve_limit: int = 5,
) -> bool:
    """Return True if the experiment loop should terminate."""
    if iteration >= max_iters:
        return True
    if consecutive_no_improve >= no_improve_limit:
        return True
    return False


def update_best(state: dict[str, Any]) -> dict[str, Any]:
    """Update best_rtt and consecutive_no_improve based on latest RTT.

    Mutates and returns the state dict.
    """
    rtt_history = state.get("rtt_history", [])
    current_rtt = rtt_history[-1] if rtt_history else 0.0

    if current_rtt > state.get("best_rtt", 0.0):
        state["best_rtt"] = current_rtt
        state["consecutive_no_improve"] = 0
    else:
        state["consecutive_no_improve"] = state.get("consecutive_no_improve", 0) + 1
    return state
