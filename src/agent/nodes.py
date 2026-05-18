"""LangGraph node functions for the closed-loop network experiment agent."""
import random
from typing import Any

from jinja2 import Environment, FileSystemLoader

from src.tools.ping_rtt_tool import ping_rtt_tool
from src.tools.traffic_send_tool import traffic_send_tool, MAX_PPS, MAX_DURATION_S, MAX_PACKET_SIZE, MAX_FLOW_COUNT, MAX_IAT_JITTER_MS
from src.tools.log_tool import log_tool
from src.tools.pcap_profile_tool import pcap_profile_tool
from src.agent.state import compute_reward, update_best
from src.llm.client import LLMClient, LLMClientError
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

_PARAM_LIMITS: dict[str, tuple[int, int]] = {
    "dst_port": (1, 65535),
    "duration_s": (1, MAX_DURATION_S),
    "pps": (1, MAX_PPS),
    "packet_size": (1, MAX_PACKET_SIZE),
    "flow_count": (1, MAX_FLOW_COUNT),
    "iat_jitter_ms": (0, MAX_IAT_JITTER_MS),
}

# Module-level cache for the rendered system prompt
_SYSTEM_PROMPT_CACHE: str | None = None


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(value, hi))


# ── LLM plan_params helpers ──────────────────────────────────────────────────

def _get_llm_client() -> LLMClient | None:
    """Create an LLMClient; return None if DEEPSEEK_API_KEY is not set.

    Can be mocked in tests via ``unittest.mock.patch``.
    """
    try:
        return LLMClient()
    except LLMClientError:
        return None


def _get_system_prompt() -> str:
    """Return the rendered system prompt, caching it at module level."""
    global _SYSTEM_PROMPT_CACHE
    if _SYSTEM_PROMPT_CACHE is None:
        env = Environment(loader=FileSystemLoader("src/prompts"))
        template = env.get_template("plan_params.j2")
        _SYSTEM_PROMPT_CACHE = template.render(
            max_pps=MAX_PPS,
            max_duration_s=MAX_DURATION_S,
            max_packet_size=MAX_PACKET_SIZE,
            max_flow_count=MAX_FLOW_COUNT,
            max_iat_jitter_ms=MAX_IAT_JITTER_MS,
        )
    return _SYSTEM_PROMPT_CACHE


def _build_llm_messages(state: dict[str, Any], prev_params: dict[str, Any]) -> list[dict]:
    """Render system + context templates and return a messages list for the LLM."""
    rtt_history = state.get("rtt_history", [])
    loss_history = state.get("loss_history", [])
    it = state.get("iteration", 0)

    # Build history entries with rewards
    history: list[dict[str, Any]] = []
    base_idx = it - len(rtt_history)
    for i, (rtt, loss) in enumerate(zip(rtt_history, loss_history)):
        history.append({
            "iteration": base_idx + i,
            "rtt": rtt,
            "loss": loss,
            "reward": compute_reward(rtt, loss),
        })

    env = Environment(loader=FileSystemLoader("src/prompts"))
    context_tpl = env.get_template("plan_params_context.j2")
    context_msg = context_tpl.render(
        iteration=it,
        max_iters=state.get("max_iters", 20),
        best_rtt=state.get("best_rtt", 0.0),
        consecutive_no_improve=state.get("consecutive_no_improve", 0),
        no_improve_limit=state.get("no_improve_limit", 5),
        reward=state.get("reward", 0.0),
        current_params=prev_params,
        history=history[-10:],  # last 10 rounds
    )

    return [
        {"role": "system", "content": _get_system_prompt()},
        {"role": "user", "content": context_msg},
    ]


def _clamp_params(raw_params: dict[str, Any], prev_params: dict[str, Any]) -> dict[str, Any]:
    """Validate, clamp, and fill missing keys in LLM-returned parameters."""
    clamped: dict[str, Any] = {}
    for key, default in DEFAULT_PARAMS.items():
        lo, hi = _PARAM_LIMITS.get(key, (1, 99999))
        raw = raw_params.get(key)

        if raw is None:
            clamped[key] = prev_params.get(key, default)
            continue

        try:
            val = int(raw)
        except (ValueError, TypeError):
            clamped[key] = prev_params.get(key, default)
            continue

        clamped[key] = _clamp(val, lo, hi)
    return clamped


def _llm_plan_params(state: dict[str, Any], prev_params: dict[str, Any]) -> dict[str, Any]:
    """Use DeepSeek LLM to generate next parameters.

    Raises LLMClientError / ValueError on failure so caller can fall back.
    """
    client = _get_llm_client()
    if client is None:
        raise LLMClientError("LLM client unavailable — no API key")

    messages = _build_llm_messages(state, prev_params)
    response = client.chat(messages)

    raw_params = response.get("params")
    if not isinstance(raw_params, dict):
        raise ValueError("LLM response missing 'params' dict")

    return _clamp_params(raw_params, prev_params)


def _random_perturbation(prev_params: dict[str, Any]) -> dict[str, Any]:
    """Fallback: randomly perturb each parameter by ±20% with 50% probability."""
    new_params: dict[str, Any] = {}
    for key, default in DEFAULT_PARAMS.items():
        old_val = prev_params.get(key, default)
        lo, hi = _PARAM_LIMITS.get(key, (1, 99999))

        if random.random() < 0.5:
            delta = int(old_val * random.uniform(-0.2, 0.2))
            new_val = _clamp(old_val + delta, lo, hi)
        else:
            new_val = old_val

        new_params[key] = new_val
    return new_params


# ── PCAP profiling node ──────────────────────────────────────────────────────

def _pcap_initial_params(pcap_profile: dict[str, Any]) -> dict[str, Any]:
    """Derive initial traffic parameters from PCAP analysis results.

    Falls back to DEFAULT_PARAMS when pcap_profile is empty or lacks data.
    """
    params = dict(DEFAULT_PARAMS)
    if not pcap_profile:
        return params

    iat_stats = pcap_profile.get("iat_ms_stats", {})
    if iat_stats.get("p50", 0) > 0:
        jitter = min(int(iat_stats["p50"]), MAX_IAT_JITTER_MS)
        params["iat_jitter_ms"] = max(0, jitter)

    top_ports = pcap_profile.get("top_dst_ports", [])
    if top_ports:
        params["dst_port"] = int(top_ports[0])

    hist = pcap_profile.get("packet_size_hist", {})
    if hist:
        peak_size = max(
            hist,
            key=lambda k: hist.get(k, 0) if isinstance(hist.get(k), (int, float)) else 0,
        )
        try:
            size = int(peak_size)
            if 1 <= size <= MAX_PACKET_SIZE:
                params["packet_size"] = size
        except (ValueError, TypeError):
            pass

    flow_stats = pcap_profile.get("flow_stats", {})
    approx_flows = flow_stats.get("approx_flow_count", 0)
    if approx_flows > 0:
        params["flow_count"] = _clamp(approx_flows // 2, 1, MAX_FLOW_COUNT)

    return params


def pcap_profile(state: dict[str, Any]) -> dict[str, Any]:
    """Analyze PCAP file and store baseline traffic characteristics.

    Only runs when iteration is 0 and a pcap_path is configured.
    Subsequent calls are no-ops.
    """
    iteration = state.get("iteration", 0)
    pcap_path = state.get("pcap_path", "")

    if iteration != 0 or not pcap_path:
        return {}

    result = pcap_profile_tool(pcap_path=pcap_path)
    return {"pcap_profile": result}


# ── plan_params ─────────────────────────────────────────────────────────────

def plan_params(state: dict[str, Any]) -> dict[str, Any]:
    """Generate next candidate traffic parameters.

    Iteration 0 derives initial params from PCAP profile when available,
    falling back to DEFAULT_PARAMS.  Subsequent iterations try the DeepSeek
    LLM first, falling back to random perturbation on any error.
    """
    iteration = state.get("iteration", 0)
    prev_params = state.get("traffic_params", {})

    if iteration == 0 or not prev_params:
        pcap = state.get("pcap_profile", {})
        return {"traffic_params": _pcap_initial_params(pcap)}

    try:
        params = _llm_plan_params(state, prev_params)
    except Exception:
        params = _random_perturbation(prev_params)

    return {"traffic_params": params}


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
