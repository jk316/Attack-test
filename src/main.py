"""CLI entry point for the closed-loop network experiment agent."""
import argparse
import json
import sys
from uuid import uuid4

from src.agent.state import check_stop_condition
from src.agent.graph import build_graph
from langgraph.errors import GraphInterrupt
from langgraph.types import Command


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


def main() -> None:
    args = parse_args()

    print(f"=== Closed-Loop Experiment ===")
    print(f"Target: {args.target_ip}")
    print(f"Log:    {args.log_path}")
    print(f"Max iterations: {args.max_iters}")
    print(f"No-improve limit: {args.no_improve_limit}")
    print()

    state = {
        "iteration": 0,
        "traffic_params": {},
        "rtt_history": [],
        "loss_history": [],
        "best_rtt": 0.0,
        "consecutive_no_improve": 0,
        "reward": 0.0,
        "target_ip": args.target_ip,
        "log_path": args.log_path,
        "messages": [],
    }

    graph = build_graph()
    thread_id = str(uuid4())[:8]
    config = {"configurable": {"thread_id": thread_id}}

    print(f"Thread: {thread_id}")
    print()

    while True:
        try:
            result = graph.invoke(state, config)
            break
        except GraphInterrupt:
            response = input("[HITL] Approve traffic send? (y/n): ").strip().lower()
            approved = response == "y"
            graph.invoke(Command(resume=approved), config)

    print()
    print("=== Experiment Complete ===")
    print(f"Iterations:       {result.get('iteration', 'N/A')}")
    print(f"Best RTT:         {result.get('best_rtt', 'N/A')} ms")
    print(f"No-improve count: {result.get('consecutive_no_improve', 'N/A')}")
    print(f"Final reward:     {result.get('reward', 'N/A')}")

    rtt_history = result.get("rtt_history", [])
    if rtt_history:
        print(f"RTT history ({len(rtt_history)} rounds): {[round(v, 2) for v in rtt_history]}")

    print(f"Results logged to: {args.log_path}")


if __name__ == "__main__":
    main()
