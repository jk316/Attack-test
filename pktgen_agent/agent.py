"""
Pktgen Agent — LangChain V1.0 agent for Pktgen traffic generation.

Uses langchain.agents.create_agent (backed by LangGraph StateGraph)
with native tool calling instead of the legacy ReAct text format.

Usage:
    # Dry-run (default): compile skills to Lua without connecting to Pktgen
    python -m pktgen_agent.agent

    # Live mode: connect to a running Pktgen instance
    python -m pktgen_agent.agent --live

    # Custom host / model
    python -m pktgen_agent.agent --live --host 192.168.1.100 --model deepseek-v4-flash
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import List

from pktgen_agent.config import load_dotenv, require_env, setup_logging
from pktgen_agent.topology import load_topology_config
from pktgen_agent.agent_prompt import SYSTEM_PROMPT, get_tool_catalog
from pktgen_agent.tools import create_tools

logger = logging.getLogger(__name__)


def check_dependencies() -> tuple[bool, str]:
    """Verify required packages are installed."""
    missing: list[str] = []
    for pkg, import_name in [
        ("pyyaml", "yaml"),
        ("langchain-core", "langchain_core"),
        ("langchain", "langchain.agents"),
        ("langchain-openai", "langchain_openai"),
        ("pydantic", "pydantic"),
    ]:
        try:
            __import__(import_name)
        except ImportError:
            missing.append(pkg)
    if missing:
        return False, (
            f"Missing packages: {', '.join(missing)}\n"
            f"  pip install {' '.join(missing)}"
        )
    return True, ""


def get_model(model_name: str) -> "BaseChatModel":
    """Create a LangChain V1.0 chat model for DeepSeek (OpenAI-compatible API).

    Returns a provider-agnostic model via init_chat_model (V1.0 best practice).
    """
    from langchain.chat_models import init_chat_model

    load_dotenv()
    api_key = require_env("DEEPSEEK_API_KEY")

    return init_chat_model(
        model=model_name,
        model_provider="openai",
        api_key=api_key,
        base_url="https://api.deepseek.com",
        temperature=0,
    )


def create_pktgen_agent(
    model: "BaseChatModel",
    tools: list,
) -> "Runnable":
    """Create a LangChain V1.0 agent for Pktgen control.

    Uses create_agent (LangGraph-backed) with native tool calling.
    No PromptTemplate, AgentExecutor, or string-based ReAct format needed.

    Args:
        model: LangChain chat model (from get_model).
        tools: List of tools from create_tools().

    Returns:
        A compiled LangGraph agent (Runnable).
    """
    from langchain.agents import create_agent

    agent = create_agent(
        model=model,
        tools=tools,
        system_prompt=SYSTEM_PROMPT,
    )
    logger.info("Agent created with %d tools", len(tools))
    return agent


def _safe_input(prompt: str = "") -> str:
    """Like input() but handles non-UTF-8 locales safely via stderr prompt and
    binary stdin read with explicit UTF-8 decode.

    On servers with LC_ALL=C / zh_CN.GBK, Python's input() uses the locale
    encoding which cannot decode Chinese characters, leading to
    UnicodeDecodeError.  This bypasses the locale entirely.
    """
    if prompt:
        # Write prompt to stderr so it never mixes with stdout redirects
        print(prompt, end="", flush=True, file=sys.stderr)
    try:
        raw = sys.stdin.buffer.readline()
        if not raw:
            raise EOFError
        return raw.decode("utf-8").rstrip("\n")
    except UnicodeDecodeError:
        # If the user's input still isn't valid UTF-8, try replacing bad bytes
        return raw.decode("utf-8", errors="replace").rstrip("\n")


def run_interactive(agent: "Runnable") -> None:
    """Run the interactive REPL loop.

    Args:
        agent: Compiled LangGraph agent from create_pktgen_agent.
    """
    logger.info("Starting interactive REPL")
    print("\nEnter a traffic generation request, or Ctrl+C / 'quit' to exit.\n")

    while True:
        try:
            cmd = _safe_input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if not cmd:
            continue
        if cmd.lower() in ("quit", "exit", "q"):
            print("Goodbye.")
            break

        try:
            # V1.0 input format: {"messages": [...]} instead of {"input": cmd}
            result = agent.invoke({
                "messages": [{"role": "user", "content": cmd}]
            })
            # V1.0 output: result["messages"][-1].content instead of result["output"]
            messages = result.get("messages", [])
            if messages:
                last_msg = messages[-1]
                output = getattr(last_msg, "content", str(last_msg))
                print(f"\n{output}\n")
            else:
                print("\n(no response)\n")
        except Exception:
            logger.exception("Error during agent invocation")
            print(f"\nError processing request. Check logs for details.\n")


def main(argv: List[str] | None = None) -> int:
    """Main entry point.

    Args:
        argv: Command-line arguments (default: sys.argv).

    Returns:
        Exit code (0 = success, 1 = error).
    """
    parser = argparse.ArgumentParser(
        description="Pktgen Agent — control a DPDK packet generator with natural language.",
    )
    parser.add_argument(
        "--live", action="store_true", default=False,
        help="Execute against a running Pktgen instance (default: dry-run)",
    )
    parser.add_argument(
        "--host", type=str, default=None,
        help="Pktgen hostname or IP (default: from topology.yaml)",
    )
    parser.add_argument(
        "--port", type=int, default=None,
        help="Pktgen TCP port (default: from topology.yaml)",
    )
    parser.add_argument(
        "--model", type=str, default="deepseek-v4-flash",
        help="DeepSeek model name (default: deepseek-v4-flash)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", default=False,
        help="Enable debug logging",
    )
    args = parser.parse_args(argv)

    # Configure logging
    setup_logging(level=logging.DEBUG if args.verbose else logging.INFO)

    # Dependency check
    ok, msg = check_dependencies()
    if not ok:
        logger.error("Dependency check failed: %s", msg)
        print(msg, file=sys.stderr)
        return 1

    # Resolve host/port
    default_host, default_port = load_topology_config()
    host = args.host or default_host
    port = args.port or default_port
    dry_run = not args.live

    # Startup messages
    mode_str = "DRY-RUN" if dry_run else f"LIVE → {host}:{port}"
    print(f"Pktgen Agent — {mode_str}")
    print(f"Model: {args.model}")

    # Show tool catalogue
    tool_catalog = get_tool_catalog()
    if tool_catalog:
        print(f"\nAvailable tools:\n{tool_catalog}\n")

    # Create tools (lazy — first call triggers filesystem scan)
    tools = create_tools(
        pktgen_host=host, pktgen_port=port, dry_run=dry_run
    )
    print(f"Tools loaded: {len(tools)} skills")

    # Create model and agent
    try:
        model = get_model(args.model)
    except RuntimeError as e:
        logger.error("Model creation failed: %s", e)
        print(f"Error: {e}", file=sys.stderr)
        return 1

    agent = create_pktgen_agent(model, tools)

    # Run interactive loop
    run_interactive(agent)
    return 0


if __name__ == "__main__":
    sys.exit(main())
