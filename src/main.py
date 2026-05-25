"""CLI entry point for the closed-loop network experiment agent."""
import argparse
import json
import sys
from pathlib import Path
from uuid import uuid4

# Ensure the project root is on sys.path so `src` is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent.graph import build_graph  # noqa: E402
from langgraph.types import Command  # noqa: E402
from langchain_core.callbacks import BaseCallbackHandler  # noqa: E402
from langchain_core.messages import AIMessage, ToolMessage  # noqa: E402

# ── Callback: log full LLM I/O ──────────────────────────────────────
class VerboseCallback(BaseCallbackHandler):
    """Print every LLM prompt (messages) and response for debugging."""

    def on_chat_model_start(self, serialized, messages, **kwargs):
        print("\n" + "=" * 70)
        print("[LLM INPUT] Messages sent to model:")
        print("-" * 40)
        for i, msg in enumerate(messages[0]):
            role = getattr(msg, "type", "unknown")
            content = getattr(msg, "content", str(msg))
            # Truncate very long content
            if isinstance(content, str) and len(content) > 2000:
                content = content[:2000] + "\n... [truncated]"
            print(f"  [{i}] {role}: {content}")
            # Show tool_call_id for tool messages
            tool_call_id = getattr(msg, "tool_call_id", None)
            if tool_call_id:
                print(f"       tool_call_id={tool_call_id}")
            # Show additional_kwargs (e.g. reasoning_content, tool_calls)
            extra = getattr(msg, "additional_kwargs", None)
            if extra:
                print(f"       additional_kwargs={json.dumps(extra, ensure_ascii=False, default=str)[:500]}")
        print("-" * 40)

    def on_chat_model_end(self, response, **kwargs):
        print("[LLM OUTPUT] Model response:")
        print("-" * 40)
        msg = response.generations[0][0].message
        content = getattr(msg, "content", "")
        if content:
            if isinstance(content, str) and len(content) > 2000:
                content = content[:2000] + "\n... [truncated]"
            print(f"  content: {content}")
        extra = getattr(msg, "additional_kwargs", None)
        if extra:
            print(f"  additional_kwargs={json.dumps(extra, ensure_ascii=False, default=str)[:500]}")
        tool_calls = getattr(msg, "tool_calls", None)
        if tool_calls:
            for tc in tool_calls:
                print(f"  tool_call: name={tc.get('name')} id={tc.get('id','?')[:8]}.. args={json.dumps(tc.get('args',{}), ensure_ascii=False)[:300]}")
        print("=" * 70 + "\n")

    def on_tool_start(self, serialized, input_str, **kwargs):
        print(f"[TOOL START] {serialized.get('name', '?')} input={str(input_str)[:300]}")

    def on_tool_end(self, output, **kwargs):
        out = json.dumps(output, ensure_ascii=False, default=str)
        print(f"[TOOL END]   output={out[:500]}")


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

    verbose = VerboseCallback()
    graph = build_graph()
    thread_id = str(uuid4())[:8]
    config = {"configurable": {"thread_id": thread_id}, "callbacks": [verbose]}

    initial_state = {"messages": [{"role": "user", "content": _build_user_message(args)}]}

    print(f"Thread: {thread_id}")
    print()

    # Start the agent — runs until first interrupt (HITL on traffic_send)
    graph.invoke(initial_state, config)

    # Poll for interrupts and resume with HITL approval
    while True:
        gs = graph.get_state(config)
        if not gs or not gs.next:
            break  # graph completed

        # Display context for the human operator
        print(f"[HITL] Traffic send requested")
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


if __name__ == "__main__":
    main()
