"""CLI entry point for the closed-loop network experiment agent."""
import argparse
import json
import logging
import sys
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger("agent")

# Ensure the project root is on sys.path so `src` is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent.graph import build_graph  # noqa: E402
from src.tools.ping_monitor import get_ping_monitor  # noqa: E402
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
            content_preview = str(getattr(msg, "content", ""))[:80].replace("\n", "\\n")
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
            logger.debug("  args: %s", json.dumps(t.get("args", {}), ensure_ascii=False)[:300])
        content = getattr(msg, "content", "")
        if content:
            logger.debug("  content: %s", content[:300])
        extra = getattr(msg, "additional_kwargs", None) or {}
        if extra:
            logger.debug("  kwargs=%s", json.dumps(extra, ensure_ascii=False, default=str)[:300])
        logger.info("=" * 60)

    # def on_tool_start(self, serialized, input_str, **kwargs):
    #     logger.info("[TOOL] %s — start", serialized.get("name", "?"))

    # def on_tool_end(self, output, **kwargs):
    #     logger.info("[TOOL] done")


CONFIG_PATH = Path(__file__).resolve().parent / "config" / "experiment.json"

DEFAULTS: dict = {
    "target_ip": "10.99.80.160",
    "pcap_path": "",
    "log_path": "data/experiment.jsonl",
    "max_iters": 20,
    "no_improve_limit": 5,
}


def _load_config_defaults() -> dict:
    """Load experiment defaults from config file, falling back to hardcoded values."""
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r") as f:
                data = json.load(f)
            return {k: data.get(k, DEFAULTS[k]) for k in DEFAULTS}
        except (json.JSONDecodeError, OSError):
            pass
    return dict(DEFAULTS)


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
        default=cfg["max_iters"],
        help="Maximum iterations (default 20)",
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
        default=False,
        help="Auto-approve all HITL traffic send requests (skip interactive prompts)",
    )
    return parser.parse_args()


def _build_user_message(args: argparse.Namespace) -> str:
    """Build the initial user message with experiment parameters."""
    pcap_line = (
        f"- PCAP文件路径: {args.pcap_path}\n"
        if args.pcap_path
        else "- PCAP文件路径: 无（使用默认初始参数）\n"
    )
    return (
        "请开始闭环网络实验：\n"
        f"- 目标IP: {args.target_ip}\n"
        f"- 最大迭代次数: {args.max_iters}\n"
        f"- 无改善停止轮数: {args.no_improve_limit}\n"
        f"- 日志文件路径: {args.log_path}\n"
        + pcap_line +
        "\n请严格按照系统提示中的实验协议执行。"
        "如果提供了PCAP文件，先用 pcap_profile 工具分析流量特征。"
    )


def main() -> None:
    args = parse_args()

    print(f"=== Closed-Loop Experiment ===")
    print(f"Target:     {args.target_ip}")
    print(f"PCAP:       {args.pcap_path or '(none)'}")
    print(f"Log:        {args.log_path}")
    print(f"Max iters:  {args.max_iters}")
    print(f"Stop after: {args.no_improve_limit} rounds no improvement")
    print()

    # ── Logging: info → console; debug → file (agent logger only) ──
    log_fh = logging.FileHandler("data/agent.log", encoding="utf-8")
    log_fh.setLevel(logging.DEBUG)
    log_fh.setFormatter(logging.Formatter("%(message)s"))
    log_ch = logging.StreamHandler()
    log_ch.setLevel(logging.INFO)
    log_ch.setFormatter(logging.Formatter("%(message)s"))

    agent_logger = logging.getLogger("agent")
    agent_logger.setLevel(logging.DEBUG)
    agent_logger.addHandler(log_ch)
    agent_logger.addHandler(log_fh)
    agent_logger.propagate = False  # don't bubble to root, keep other libs quiet

    verbose = VerboseCallback()
    graph = build_graph()
    thread_id = str(uuid4())[:8]
    config = {"configurable": {"thread_id": thread_id}, "callbacks": [verbose]}

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

            # Display context for the human operator
            print(f"[HITL] Traffic send requested")
            if args.auto_approve:
                approved = True
                print("  Auto-approved (--auto-approve)")
            else:
                try:
                    response = input("  Approve traffic send? (y/n): ").strip().lower()
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

        print(f"\nResults logged to: {args.log_path}")
    finally:
        # Ensure ping monitor is always cleaned up
        try:
            monitor = get_ping_monitor()
            if monitor.is_running():
                logger.info("Cleaning up ping monitor...")
                monitor.stop()
        except Exception:
            pass


if __name__ == "__main__":
    main()
