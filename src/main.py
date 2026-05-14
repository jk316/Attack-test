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
        "max_iters": args.max_iters,
        "no_improve_limit": args.no_improve_limit,
        "messages": [],
    }

    graph = build_graph()
    thread_id = str(uuid4())[:8]
    config = {"configurable": {"thread_id": thread_id}}

    print(f"Thread: {thread_id}")
    print()

    # Start the graph — runs until the first interrupt (send_traffic)
    graph.invoke(state, config)

    # Poll for interrupts and resume with HITL approval
    while True:
        gs = graph.get_state(config)
        if not gs or not gs.next:
            break  # graph completed

        print(f"[Round {gs.values.get('iteration', 0) + 1}]")
        print(f"  Params: pps={gs.values.get('traffic_params', {}).get('pps')}, "
              f"size={gs.values.get('traffic_params', {}).get('packet_size')}, "
              f"flows={gs.values.get('traffic_params', {}).get('flow_count')}")
        try:
            response = input("  [HITL] Approve traffic send? (y/n): ").strip().lower()
        except EOFError:
            print("  [HITL] No input — rejecting by default")
            response = "n"
        approved = response == "y"
        graph.invoke(Command(resume=approved), config)
        print()

    # Get final state
    final_state = graph.get_state(config)
    result = final_state.values if final_state else {}

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
