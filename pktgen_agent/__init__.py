"""
Pktgen Agent — AI agent controller for Pktgen-DPDK (LangChain V1.0).

Translates natural language traffic-generation requests into executable
Lua scripts via a Skill DSL compiler, then sends them to a running
Pktgen instance over TCP.

Quick start::

    from pktgen_agent import create_pktgen_agent, get_model, create_tools

    model = get_model("deepseek-v4-flash")
    tools = create_tools()
    agent = create_pktgen_agent(model, tools)

    result = agent.invoke({
        "messages": [{"role": "user", "content": "Send UDP at 80% rate"}]
    })
"""

from __future__ import annotations

# Lazy imports via __getattr__ to avoid importing submodules at package
# load time.  This prevents the runpy RuntimeWarning when running
# ``python -m pktgen_agent.agent`` (the package import would otherwise
# eagerly load agent.py, causing it to appear in sys.modules before
# runpy registers it as __main__).

_ATTR_MODULE_MAP: dict[str, str] = {
    # Agent
    "check_dependencies":     "pktgen_agent.agent",
    "create_pktgen_agent":    "pktgen_agent.agent",
    "get_model":              "pktgen_agent.agent",
    "main":                   "pktgen_agent.agent",
    "run_interactive":        "pktgen_agent.agent",
    # Prompt
    "SYSTEM_PROMPT":          "pktgen_agent.agent_prompt",
    "get_tool_catalog":       "pktgen_agent.agent_prompt",
    # Client
    "PktgenClient":           "pktgen_agent.client",
    "PktgenConnectionError":  "pktgen_agent.client",
    "execute_lua":            "pktgen_agent.client",
    # Compiler
    "SkillCompiler":          "pktgen_agent.compiler",
    "CompileError":           "pktgen_agent.compiler",
    "compile_skill":          "pktgen_agent.compiler",
    # Config
    "load_dotenv":            "pktgen_agent.config",
    "require_env":            "pktgen_agent.config",
    "setup_logging":          "pktgen_agent.config",
    # Topology
    "load_topology_config":   "pktgen_agent.topology",
    # Tools (public factory)
    "create_tools":           "pktgen_agent.tools",
}


def __getattr__(name: str):
    """Defer submodule imports until the attribute is first accessed."""
    if name in _ATTR_MODULE_MAP:
        import importlib

        mod = importlib.import_module(_ATTR_MODULE_MAP[name])
        attr = getattr(mod, name)
        # Cache in the module's global namespace for fast subsequent access
        globals()[name] = attr
        return attr
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = list(_ATTR_MODULE_MAP.keys())
