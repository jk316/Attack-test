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
    best_reward: float
    """Best (highest) reward observed so far, initialized to 0.0.

    Reward uses the unified formula: reward = avg_rtt_ms + loss_pct × 10
    (see data-model 校验规则「奖励公式唯一」).
    """

    consecutive_no_improve: int
    """Counter: increments when reward does not exceed best_reward."""

    reward: float
    """Current reward = avg_rtt_ms + loss_pct × 10 (unified formula)."""

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

    # ── Continuous ping monitoring state ───────────────────────
    ping_monitor_active: bool
    """Whether the background ping monitor has been started."""

    baseline_rtt: float
    """Pre-attack RTT measured by read_ping_stats before traffic_send."""

    rtt_during_attack: list[dict]
    """RTT time-series samples collected during the most recent traffic_send."""

    # ── ReAct conversation and tool-calling ─────────────────────
    messages: Annotated[list, add_messages]
    """LLM conversation history with tool call/result pairs."""


def compute_reward(avg_rtt_ms: float, loss_pct: float) -> float:
    """Compute the unified reward: avg_rtt_ms + loss_pct * 10.

    Loss is a positive attack signal (DoS effect), matching the system
    prompt formula and data-model 校验规则「奖励公式唯一」。Returns 0.0 if
    avg_rtt_ms is inf (all probes lost — no usable RTT sample).
    """
    if avg_rtt_ms == float('inf'):
        return 0.0
    return avg_rtt_ms + loss_pct * 10


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


def apply_observation(
    state: dict[str, Any],
    observation: dict[str, Any] | None,
) -> dict[str, Any]:
    """应用一轮实测观测到硬裁决状态（G1、D1、D5）。

    Args:
        state: 裁决状态 dict，维护 ``best_reward`` 与 ``consecutive_no_improve``。
        observation: 归一化观测 ``{avg_rtt_ms, loss_pct, covers_attack_window}``。
            ``None``（本轮无观测）或 ``covers_attack_window=False``（观测未
            覆盖攻击窗口）时本轮不计入无改善判定（D5），状态保持不变。

    Returns:
        更新后的 state；``state["last_round_counted"]`` 标记本轮是否计入。
    """
    if not observation:
        state["last_round_counted"] = False
        return state
    covers = observation.get("covers_attack_window", True)
    avg = observation.get("avg_rtt_ms")
    if not covers or avg is None:
        state["last_round_counted"] = False
        return state
    loss = observation.get("loss_pct", 0.0)
    state["reward"] = compute_reward(float(avg), float(loss))
    update_best(state)
    state["last_round_counted"] = True
    return state


def update_best(state: dict[str, Any]) -> dict[str, Any]:
    """Update best_reward and consecutive_no_improve based on current reward.

    Reads the current round's reward from ``state["reward"]`` (computed via
    :func:`compute_reward` from measured avg_rtt_ms / loss_pct). An
    improvement (reward > best_reward) resets the counter to 0; otherwise
    the counter increments by 1 (data-model 校验规则：改善归零 / 无改善 +1).

    Mutates and returns the state dict.
    """
    reward = state.get("reward", 0.0)
    best_reward = state.get("best_reward", 0.0)

    if reward > best_reward:
        state["best_reward"] = reward
        state["consecutive_no_improve"] = 0
    else:
        state["best_reward"] = best_reward
        state["consecutive_no_improve"] = state.get("consecutive_no_improve", 0) + 1
    return state
