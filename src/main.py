"""CLI entry point for the closed-loop network experiment agent."""
import argparse
import sys
from pathlib import Path
from uuid import uuid4

# Ensure the project root is on sys.path so `src` is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent.graph import build_graph  # noqa: E402
from langgraph.types import Command  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Closed-Loop Network Experiment Agent"
    )
    parser.add_argument(
        "--target-ip",
        default="10.99.80.160",
        help="Target IP for traffic and ping (must be in allowlist)",
    )
    parser.add_argument(
        "--pcap-path",
        default="",
        help="Path to PCAP/PCAPng file for baseline traffic profiling",
    )
    parser.add_argument(
        "--log-path",
        default="data/experiment.jsonl",
        help="Path to JSONL experiment log",
    )
    parser.add_argument(
        "--max-iters",
        type=int,
        default=20,
        help="Maximum iterations (default 20)",
    )
    parser.add_argument(
        "--no-improve-limit",
        type=int,
        default=5,
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

    graph = build_graph()
    thread_id = str(uuid4())[:8]
    config = {"configurable": {"thread_id": thread_id}}

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
