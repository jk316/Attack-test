"""CLI entry point for the closed-loop network experiment agent."""
import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger("agent")

# Console preview length for message content in [LLM INPUT] lines.
# Full untruncated content always goes to data/agent-YYYY-MM-DD.log at DEBUG.
MSG_PREVIEW_LEN = 500

# Ensure the project root is on sys.path so `src` is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent.graph import build_graph  # noqa: E402
from src.pktgen.adapter import get_pktgen_host, get_pktgen_port  # noqa: E402
from src.tools.log_tool import generate_run_id  # noqa: E402
from src.trex.config import get_trex_host, get_trex_port  # noqa: E402
from src.tools.monitor_lifecycle import (  # noqa: E402
    start_experiment_monitors,
    stop_experiment_monitors,
)
from langgraph.types import Command  # noqa: E402
from langchain_core.callbacks import BaseCallbackHandler  # noqa: E402
from langchain_core.messages import AIMessage, ToolMessage  # noqa: E402

# ── Callback: log LLM I/O via logging module ────────────────────────
class VerboseCallback(BaseCallbackHandler):
    """Log LLM prompts and responses. Level: INFO=tool calls/structure, DEBUG=full content."""

    def __init__(self):
        super().__init__()
        self._last_msg_count = 0

    @staticmethod
    def _flat_tool_calls(msg) -> list[str]:
        tc_list = getattr(msg, "tool_calls", None) or []
        return [tc.get("name", "?") for tc in tc_list]

    def on_chat_model_start(self, serialized, messages, **kwargs):
        msgs = messages[0]
        last = self._last_msg_count
        new_msgs = msgs[last:]
        logger.info("=" * 60)
        logger.info("[LLM INPUT] 总消息: %d, 本轮新增: %d", len(msgs), len(new_msgs))
        for i, msg in enumerate(new_msgs):
            idx = last + i
            role = getattr(msg, "type", "unknown")
            raw_content = str(getattr(msg, "content", ""))
            content_preview = raw_content[:MSG_PREVIEW_LEN].replace("\n", "\\n")
            if len(raw_content) > MSG_PREVIEW_LEN:
                content_preview += f"… (+{len(raw_content) - MSG_PREVIEW_LEN} chars, see data/agent-YYYY-MM-DD.log)"
            tc = self._flat_tool_calls(msg)
            extra_info = f" tool_calls={tc}" if tc else ""
            logger.info("  [%d] %s: %s %s", idx, role, content_preview, extra_info)
            logger.debug("    content: %s", str(getattr(msg, "content", "")))
            extra = getattr(msg, "additional_kwargs", None) or {}
            if extra:
                logger.debug("    kwargs=%s", json.dumps(extra, ensure_ascii=False, default=str))
        self._last_msg_count = len(msgs)

    def on_chat_model_end(self, response, **kwargs):
        msg = response.generations[0][0].message
        tc = self._flat_tool_calls(msg)
        logger.info("[LLM OUTPUT] tool_calls=%s", tc)
        for t in getattr(msg, "tool_calls", None) or []:
            logger.debug("  args: %s", json.dumps(t.get("args", {}), ensure_ascii=False)[:MSG_PREVIEW_LEN])
        content = getattr(msg, "content", "")
        if content:
            logger.debug("  content: %s", content[:MSG_PREVIEW_LEN])
        extra = getattr(msg, "additional_kwargs", None) or {}
        if extra:
            logger.debug("  kwargs=%s", json.dumps(extra, ensure_ascii=False, default=str)[:MSG_PREVIEW_LEN])
        logger.info("=" * 60)

    # def on_tool_start(self, serialized, input_str, **kwargs):
    #     logger.info("[TOOL] %s — start", serialized.get("name", "?"))

    # def on_tool_end(self, output, **kwargs):
    #     logger.info("[TOOL] done")


CONFIG_PATH = Path(__file__).resolve().parent.parent / "experiment.json"
HTTP_PROBE_PATH = Path(__file__).resolve().parent.parent / "http_probe.json"

DEFAULTS: dict = {
    "target_ip": "10.99.80.160",
    "pcap_path": "",
    "log_path": "data/experiment.jsonl",
    "max_iters": 20,
    "no_improve_limit": 5,
    "auto_approve": False,
    "verbose": False,
    "pktgen_live": False,
    "trex_live": False,
    "trex_explore": False,
    "catalog_target": 10,
    "explore_direction": "",
    "instruction": "",
}

# Config sections read as nested dicts (attack/pktgen/trex).
_SECTION_KEYS = ("attack", "pktgen", "trex")


def _read_config_file() -> dict:
    """Read experiment.json, returning {} on missing file or parse error."""
    if not CONFIG_PATH.exists():
        return {}
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _load_http_probe_config() -> dict:
    """Read http_probe.json (dial-testing config), returning {} on any error."""
    if not HTTP_PROBE_PATH.exists():
        return {}
    try:
        with open(HTTP_PROBE_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _load_config_defaults() -> dict:
    """Load experiment defaults from config, falling back to hardcoded DEFAULTS."""
    data = _read_config_file()
    merged = dict(DEFAULTS)
    for key in DEFAULTS:
        if key in data:
            merged[key] = data[key]
    for key in _SECTION_KEYS:
        if key in data:
            merged[key] = dict(data[key])
    return merged


def parse_args() -> argparse.Namespace:
    cfg = _load_config_defaults()
    parser = argparse.ArgumentParser(
        description="Closed-Loop Network Experiment Agent"
    )
    parser.add_argument(
        "--target-ip",
        default=cfg["target_ip"],
        help="Target IP for traffic and ping (must be in allowlist)",
    )
    parser.add_argument(
        "--pcap-path",
        default=cfg["pcap_path"],
        help="Path to PCAP/PCAPng file for baseline traffic profiling",
    )
    parser.add_argument(
        "--log-path",
        default=cfg["log_path"],
        help="Path to JSONL experiment log",
    )
    parser.add_argument(
        "--max-iters",
        type=int,
        default=None,
        help="Maximum iterations (default 20; 40 in --trex-explore mode)",
    )
    parser.add_argument(
        "--no-improve-limit",
        type=int,
        default=cfg["no_improve_limit"],
        help="Stop after N consecutive rounds without improvement (default 5)",
    )
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        default=cfg["auto_approve"],
        help="Auto-approve all HITL requests (traffic send + TRex script execution), "
             "skipping interactive prompts",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        default=cfg["verbose"],
        help="Show full untruncated message content on the console (console → DEBUG). "
             "Full content is always written to data/agent-<日期>.log（按天分文件）regardless.",
    )
    # ── Attack parameter defaults ────────────────────────────────────
    attack_cfg = cfg.get("attack", {})
    parser.add_argument(
        "--duration", type=int, default=attack_cfg.get("duration_s", 5),
        help="Attack duration in seconds (default 5)",
    )
    parser.add_argument(
        "--pps", type=int, default=attack_cfg.get("pps", 100),
        help="Packets per second for Scapy tools (default 100)",
    )
    parser.add_argument(
        "--packet-size", type=int, default=attack_cfg.get("packet_size", 64),
        help="Packet payload size in bytes (default 64)",
    )
    parser.add_argument(
        "--flow-count", type=int, default=attack_cfg.get("flow_count", 1),
        help="Number of concurrent flows (default 1)",
    )
    parser.add_argument(
        "--iat-jitter", type=int, default=attack_cfg.get("iat_jitter_ms", 0),
        help="Random jitter on inter-packet interval in ms (default 0)",
    )
    # ── Pktgen-DPDK options ──────────────────────────────────────────
    pktgen_cfg = cfg.get("pktgen", {})
    parser.add_argument(
        "--pktgen-live",
        action="store_true",
        default=cfg["pktgen_live"],
        help="Run Pktgen tools in live mode (actually send traffic to Pktgen). "
             "Default is dry-run (compile Lua scripts only).",
    )
    parser.add_argument(
        "--pktgen-host",
        default=pktgen_cfg.get("host"),
        help="Pktgen-DPDK hostname or IP (default from topology.yaml)",
    )
    parser.add_argument(
        "--pktgen-port",
        type=int,
        default=pktgen_cfg.get("port"),
        help="Pktgen-DPDK TCP control port (default from topology.yaml)",
    )
    parser.add_argument(
        "--pktgen-rate", type=float, default=pktgen_cfg.get("rate", 50),
        help="Pktgen rate as percentage 0-100 (default 50)",
    )
    parser.add_argument(
        "--pktgen-duration", type=int, default=pktgen_cfg.get("duration_ms", 10000),
        help="Pktgen duration in milliseconds (default 5000)",
    )
    # ── TRex options ─────────────────────────────────────────────────
    trex_cfg = cfg.get("trex", {})
    parser.add_argument(
        "--trex-live",
        action="store_true",
        default=cfg["trex_live"],
        help="Run TRex scripts in live mode (actually execute generated Python). "
             "Default is dry-run (write + syntax-check only).",
    )
    parser.add_argument(
        "--trex-host",
        default=trex_cfg.get("host"),
        help="TRex server hostname or IP (default from topology.yaml)",
    )
    parser.add_argument(
        "--trex-port",
        type=int,
        default=trex_cfg.get("port"),
        help="TRex server RPC port (default from topology.yaml)",
    )
    parser.add_argument(
        "--trex-timeout", type=float, default=trex_cfg.get("timeout_s", 30),
        help="Timeout in seconds for running a TRex script (default 30)",
    )
    parser.add_argument(
        "--trex-python", default=trex_cfg.get("python"),
        help="Python interpreter for running generated TRex scripts "
             "(default: current interpreter; set to a conda env with trex libs)",
    )
    parser.add_argument(
        "--trex-lib-dir", default=trex_cfg.get("lib_dir"),
        help="TRex client library source root (server path) that read_file/grep "
             "are confined to for source self-inspection",
    )
    parser.add_argument(
        "--trex-explore",
        action="store_true",
        default=cfg["trex_explore"],
        help="TRex attack catalog exploration mode: the agent only generates "
             "attack scripts with Chinese annotations (dry-run, no traffic, no "
             "HITL) and saves the catalog summary to "
             "output/trex_attack_catalog_<timestamp>.md.",
    )
    parser.add_argument(
        "--catalog-target",
        type=int,
        default=cfg["catalog_target"],
        help="Minimum number of attack scripts the agent must generate in "
             "--trex-explore mode (default 10)",
    )
    parser.add_argument(
        "--explore-direction",
        default=cfg["explore_direction"],
        help="User-specified exploration direction for --trex-explore mode, "
             "injected into the catalog prompt (free-form text, e.g. "
             '"重点探索DNS放大攻击和TCP SYN洪水")',
    )
    parser.add_argument(
        "--instruction",
        default=cfg["instruction"],
        help="用户对本次实验的额外目标/指令（自由文本，注入 user message 和 system prompt）",
    )
    # ── HTTP dial-testing options（来自独立 http_probe.json）────────
    http_cfg = _load_http_probe_config()
    parser.add_argument(
        "--http-url", default=http_cfg.get("url"),
        help="HTTP business endpoint URL for dial-testing",
    )
    parser.add_argument(
        "--http-interval", type=float, default=http_cfg.get("interval_s", 1.0),
        help="Seconds between HTTP probes (default 1.0)",
    )
    parser.add_argument(
        "--http-timeout", type=float, default=http_cfg.get("timeout_s", 5.0),
        help="Per-request HTTP timeout in seconds (default 5)",
    )
    parser.add_argument(
        "--http-method", default=http_cfg.get("method", "GET"),
        help="HTTP method for dial-testing (default GET)",
    )
    parser.add_argument(
        "--http-body", default=http_cfg.get("body"),
        help="Request body for dial-testing (e.g. JSON for POST login)",
    )
    parser.add_argument(
        "--http-content-type", default=http_cfg.get("content_type"),
        help="Content-Type header for dial-testing (e.g. application/json)",
    )
    args = parser.parse_args()
    if args.trex_explore and args.trex_live:
        parser.error(
            "--trex-explore cannot be combined with --trex-live: "
            "explore mode never executes traffic"
        )
    if args.max_iters is None:
        args.max_iters = 40 if args.trex_explore else cfg["max_iters"]
    return args


def _build_user_message(args: argparse.Namespace) -> str:
    """Build the initial user message with experiment parameters."""
    if args.trex_explore:
        direction_line = (
            f"- 探索方向: {args.explore_direction}\n"
            if args.explore_direction
            else ""
        )
        return (
            "请开始 TRex 攻击能力探索：\n"
            f"- 目标: 枚举并生成 ≥{args.catalog_target} 类攻击脚本（文件名 cat_ 开头）\n"
            + direction_line +
            "- 模式: dry-run，只生成代码与中文注释，不发送任何流量\n"
            "请严格按照系统提示中的探索协议执行（先规划 → 再生成 → 再总结）。"
        )
    instruction_line = (
        f"- 用户指令: {getattr(args, 'instruction', '')}\n"
        if getattr(args, "instruction", "")
        else ""
    )
    pcap_line = (
        f"- PCAP文件路径: {args.pcap_path}\n"
        if args.pcap_path
        else "- PCAP文件路径: 无（使用默认初始参数）\n"
    )
    return (
        "请开始闭环网络实验：\n"
        + instruction_line +
        f"- 目标IP: {args.target_ip}\n"
        f"- 最大迭代次数: {args.max_iters}\n"
        f"- 无改善停止轮数: {args.no_improve_limit}\n"
        f"- 日志文件路径: {args.log_path}\n"
        + pcap_line +
        "\n请严格按照系统提示中的实验协议执行。"
        "如果提供了PCAP文件，先用 pcap_profile 工具分析流量特征。"
    )


def _apply_mode_env(args: argparse.Namespace) -> None:
    """Apply env vars specific to the TRex explore mode (forced dry-run)."""
    if args.trex_explore:
        os.environ["TREX_DRY_RUN"] = "true"
        os.environ["CATALOG_TARGET"] = str(args.catalog_target)
        if args.explore_direction:
            os.environ["EXPLORE_DIRECTION"] = args.explore_direction


def _apply_trex_l2_env(trex_cfg: dict) -> None:
    """把 experiment.json 的 trex L2 事实注入 env（缺键不动，交由 config.py 回退）。"""
    for key in ("dst_mac", "src_mac", "start_force"):
        value = trex_cfg.get(key)
        if value is not None:
            os.environ[f"TREX_{key.upper()}"] = str(value)


def _recursion_limit(max_iters: int) -> int:
    """Graph superstep budget — must cover the prompt-level max_iters."""
    return max(25, max_iters + 5)


def _extract_hitl_payload(gs) -> dict | None:
    """Extract the HITL interrupt payload from a StateSnapshot, if any.

    Mirrors backend/experiment.py::_extract_hitl so the CLI operator sees the
    same details (message + params) that the web console shows.
    """
    for task in getattr(gs, "tasks", None) or []:
        for intr in getattr(task, "interrupts", None) or []:
            val = intr.value
            if isinstance(val, dict) and "message" in val:
                return val
    return None


def _agent_log_path() -> str:
    """Today's agent log path, daily-rotated: ``data/agent-YYYY-MM-DD.log``."""
    return f"data/agent-{datetime.now().strftime('%Y-%m-%d')}.log"


def main() -> None:
    args = parse_args()

    # ── Run identity: every log_result line in this run shares this id ──
    run_id = generate_run_id()
    os.environ["DSH_RUN_ID"] = run_id

    # ── Inject defaults as env vars (tools read these at call time) ──
    os.environ["ATK_DURATION_S"] = str(args.duration)
    os.environ["ATK_PPS"] = str(args.pps)
    os.environ["ATK_PACKET_SIZE"] = str(args.packet_size)
    os.environ["ATK_FLOW_COUNT"] = str(args.flow_count)
    os.environ["ATK_IAT_JITTER_MS"] = str(args.iat_jitter)
    os.environ["PKTGEN_RATE"] = str(args.pktgen_rate)
    os.environ["PKTGEN_DURATION_MS"] = str(args.pktgen_duration)

    # ── Pktgen-DPDK configuration ──
    if args.pktgen_live:
        os.environ["PKTGEN_DRY_RUN"] = "false"
    if args.pktgen_host is not None:
        os.environ["PKTGEN_HOST"] = args.pktgen_host
    if args.pktgen_port is not None:
        os.environ["PKTGEN_PORT"] = str(args.pktgen_port)

    # ── User instruction (experiment mode, injected into prompt) ──
    os.environ["INSTRUCTION"] = args.instruction

    # ── TRex configuration ──
    _apply_mode_env(args)
    if args.trex_live:
        os.environ["TREX_DRY_RUN"] = "false"
    # 无条件解析 host：生成脚本（trex_common.TREX_SERVER）也读 TREX_HOST，
    # 否则 topology.yaml 提供的 host 不会传到子进程。
    os.environ["TREX_HOST"] = str(args.trex_host or get_trex_host())
    if args.trex_port is not None:
        os.environ["TREX_PORT"] = str(args.trex_port)
    os.environ["TREX_TIMEOUT_S"] = str(args.trex_timeout)
    # trex L2 事实（dst_mac/src_mac/start_force）来自 experiment.json 的 trex 段
    trex_cfg = _load_config_defaults().get("trex", {})
    _apply_trex_l2_env(trex_cfg)
    if args.trex_python:
        os.environ["TREX_PYTHON"] = args.trex_python
    if args.trex_lib_dir:
        os.environ["TREX_LIB_DIR"] = args.trex_lib_dir

    # ── HTTP dial-testing configuration ──
    if args.http_url:
        os.environ["HTTP_URL"] = args.http_url
    os.environ["HTTP_INTERVAL_S"] = str(args.http_interval)
    os.environ["HTTP_TIMEOUT_S"] = str(args.http_timeout)
    os.environ["HTTP_METHOD"] = args.http_method
    if args.http_body:
        os.environ["HTTP_BODY"] = args.http_body
    if args.http_content_type:
        os.environ["HTTP_CONTENT_TYPE"] = args.http_content_type

    pktgen_host = args.pktgen_host or get_pktgen_host()
    pktgen_port = args.pktgen_port or get_pktgen_port()
    trex_host = args.trex_host or get_trex_host()
    trex_port = args.trex_port or get_trex_port()

    print(f"=== Closed-Loop Experiment ===")
    print(f"Run ID:     {run_id}")
    print(f"Target:     {args.target_ip}")
    print(f"PCAP:       {args.pcap_path or '(none)'}")
    print(f"Log:        {args.log_path}")
    print(f"Max iters:  {args.max_iters}")
    print(f"Stop after: {args.no_improve_limit} rounds no improvement")
    if args.instruction:
        print(f"Instruction: {args.instruction}")
    pktgen_mode = "live" if args.pktgen_live else "dry-run"
    print(f"Pktgen:     {pktgen_mode} ({pktgen_host}:{pktgen_port})")
    trex_mode = "live" if args.trex_live else ("explore" if args.trex_explore else "dry-run")
    print(f"Trex:       {trex_mode} ({trex_host}:{trex_port})")
    if args.trex_explore:
        catalog_path = (Path("output")
                        / f"trex_attack_catalog_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md")
        print(f"Catalog:    ≥{args.catalog_target} attack scripts → "
              f"{catalog_path} (no traffic, no HITL)")
        if args.explore_direction:
            print(f"Direction:  {args.explore_direction}")
    print()

    # ── Logging: info → console; debug → file (agent logger only) ──
    # Daily-rotated: data/agent-YYYY-MM-DD.log (new file per calendar day).
    log_fh = logging.FileHandler(_agent_log_path(), encoding="utf-8")
    log_fh.setLevel(logging.DEBUG)
    log_fh.setFormatter(logging.Formatter("%(message)s"))
    log_ch = logging.StreamHandler()
    log_ch.setLevel(logging.DEBUG if args.verbose else logging.INFO)
    log_ch.setFormatter(logging.Formatter("%(message)s"))

    agent_logger = logging.getLogger("agent")
    agent_logger.setLevel(logging.DEBUG)
    agent_logger.addHandler(log_ch)
    agent_logger.addHandler(log_fh)
    agent_logger.propagate = False  # don't bubble to root, keep other libs quiet
    agent_logger.info("[RUN START] %s", run_id)

    # ── Monitor lifecycle: program-owned, auto-started (spec 009) ──
    # Catalog mode sends no traffic and needs no observation (FR-004).
    if not args.trex_explore:
        http_cfg = None
        if args.http_url:
            http_cfg = {
                "url": args.http_url,
                "interval_s": args.http_interval,
                "timeout_s": args.http_timeout,
                "method": args.http_method,
                "body": args.http_body,
                "content_type": args.http_content_type,
            }
        started = start_experiment_monitors(args.target_ip, http_cfg)
        agent_logger.info(
            "Monitors auto-started: ping=%s http=%s",
            started["ping"], started["http"],
        )

    verbose = VerboseCallback()
    graph = build_graph(
        max_iters=args.max_iters, no_improve_limit=args.no_improve_limit,
        mode="catalog" if args.trex_explore else "experiment",
    )
    thread_id = str(uuid4())[:8]
    config = {
        "configurable": {"thread_id": thread_id},
        "callbacks": [verbose],
        "recursion_limit": _recursion_limit(args.max_iters),
    }

    initial_state = {"messages": [{"role": "user", "content": _build_user_message(args)}]}

    print(f"Thread: {thread_id}")
    print()

    try:
        # Start the agent — runs until first interrupt (HITL on traffic_send)
        graph.invoke(initial_state, config)

        # Poll for interrupts and resume with HITL approval
        while True:
            gs = graph.get_state(config)
            if not gs or not gs.next:
                break  # graph completed

            # Display the interrupt payload so the operator sees what is approved
            payload = _extract_hitl_payload(gs)
            print((payload or {}).get("message", "[HITL] Action requested"))
            if payload and payload.get("params"):
                print(json.dumps(payload["params"], ensure_ascii=False, indent=2))
            if args.auto_approve:
                approved = True
                print("  Auto-approved (--auto-approve)")
            else:
                try:
                    response = input("  Approve? (y/n): ").strip().lower()
                except EOFError:
                    print("  No input — rejecting by default")
                    response = "n"
                approved = response == "y"
                print(f"  {'Approved' if approved else 'Rejected'}")
            graph.invoke(Command(resume=approved), config)
            print()

        # Get final state
        final_state = graph.get_state(config)
        result = final_state.values if final_state else {}

        print("=== Experiment Complete ===")

        # Extract final AI message for summary
        messages = result.get("messages", [])
        if messages:
            last_msg = messages[-1]
            content = getattr(last_msg, "content", str(last_msg))
            if content:
                # Print the last meaningful content (excluding tool results)
                print("\n" + str(content))
            else:
                print("(no summary output)")

        # Catalog mode: persist the final summary as the deliverable.
        if args.trex_explore and content:
            catalog_path.parent.mkdir(parents=True, exist_ok=True)
            catalog_path.write_text(str(content), encoding="utf-8")
            print(f"\nAttack catalog saved to: {catalog_path}")

        print(f"\nResults logged to: {args.log_path}")
    finally:
        # Ensure both monitors are always cleaned up (spec 009 FR-007)
        try:
            stop_experiment_monitors()
        except Exception:
            logger.warning("Monitor cleanup failed", exc_info=True)
        agent_logger.info("[RUN END] %s", run_id)


if __name__ == "__main__":
    main()
