"""LangGraph node functions for the closed-loop network experiment agent."""
import random
from typing import Any

from src.tools.ping_rtt_tool import ping_rtt_tool
from src.tools.traffic_send_tool import traffic_send_tool, MAX_PPS, MAX_DURATION_S, MAX_PACKET_SIZE, MAX_FLOW_COUNT, MAX_IAT_JITTER_MS
from src.tools.log_tool import log_tool
from src.agent.state import compute_reward, update_best
from langgraph.types import interrupt

# Default baseline traffic parameters
DEFAULT_PARAMS: dict[str, Any] = {
    "dst_port": 8080,
    "duration_s": 5,
    "pps": 50,
    "packet_size": 64,
    "flow_count": 1,
    "iat_jitter_ms": 5,
}


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(value, hi))


def plan_params(state: dict[str, Any]) -> dict[str, Any]:
    """Generate next candidate traffic parameters via random perturbation.

    First iteration returns default params. Subsequent iterations
    perturb each dimension by ±20% with 50% probability, clamped to limits.
    """
    iteration = state.get("iteration", 0)
    prev_params = state.get("traffic_params", {})

    if iteration == 0 or not prev_params:
        return {"traffic_params": dict(DEFAULT_PARAMS)}

    limits = {
        "dst_port": (1, 65535),
        "duration_s": (1, MAX_DURATION_S),
        "pps": (1, MAX_PPS),
        "packet_size": (1, MAX_PACKET_SIZE),
        "flow_count": (1, MAX_FLOW_COUNT),
        "iat_jitter_ms": (0, MAX_IAT_JITTER_MS),
    }

    new_params: dict[str, Any] = {}
    for key, default in DEFAULT_PARAMS.items():
        old_val = prev_params.get(key, default)
        lo, hi = limits.get(key, (1, 99999))

        if random.random() < 0.5:
            delta = int(old_val * random.uniform(-0.2, 0.2))
            new_val = _clamp(old_val + delta, lo, hi)
        else:
            new_val = old_val

        new_params[key] = new_val

    return {"traffic_params": new_params}


def send_traffic(state: dict[str, Any]) -> dict[str, Any]:
    """Send UDP traffic after HITL approval.

    Calls langgraph interrupt() to pause for human confirmation,
    then calls traffic_send_tool with the current params.
    """
    params = state.get("traffic_params", {})
    target_ip = state.get("target_ip", "")

    # HITL approval gate
    approval = interrupt({
        "message": "Approve traffic send?",
        "target_ip": target_ip,
        "params": params,
    })

    if not approval:
        return {"error": "HITL rejected"}

    traffic_send_tool(
        dst_ip=target_ip,
        dst_port=params.get("dst_port", 8080),
        duration_s=params.get("duration_s", 5),
        pps=params.get("pps", 100),
        packet_size=params.get("packet_size", 64),
        flow_count=params.get("flow_count", 1),
        iat_jitter_ms=params.get("iat_jitter_ms", 0),
    )

    return {}


def measure_rtt(state: dict[str, Any]) -> dict[str, Any]:
    """Run ping against target, compute reward, append to history."""
    target_ip = state.get("target_ip", "")

    result = ping_rtt_tool(ip=target_ip)
    avg_rtt = float(result["avg_rtt_ms"])
    loss = float(result["loss_pct"])
    reward = compute_reward(avg_rtt, loss)

    return {
        "rtt_history": [avg_rtt],
        "loss_history": [loss],
        "reward": reward,
    }


def log_result(state: dict[str, Any]) -> dict[str, Any]:
    """Write this iteration's result to the JSONL log."""
    log_path = state.get("log_path", "data/experiment.jsonl")
    rtt_history = state.get("rtt_history", [])

    entry: dict[str, Any] = {
        "iteration": state.get("iteration", 0),
        "params": state.get("traffic_params", {}),
        "rtt": rtt_history[-1] if rtt_history else 0.0,
        "loss": state.get("loss_history", [0.0])[-1],
    }
    log_tool(log_path, entry)
    return {}


def update_state(state: dict[str, Any]) -> dict[str, Any]:
    """Update best_rtt, consecutive_no_improve, and increment iteration."""
    updated = update_best(dict(state))
    return {
        "best_rtt": updated["best_rtt"],
        "consecutive_no_improve": updated["consecutive_no_improve"],
        "iteration": state.get("iteration", 0) + 1,
    }
