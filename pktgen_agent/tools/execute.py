"""
Pktgen Skill Tool Factory (LangChain V1.0)
Reads dsl/skills/*.yaml and creates LangChain @tool-decorated functions.

Each tool compiles the skill → sends Lua via socket → returns result.

Usage:
    from pktgen_agent.tools.execute import create_all_tools

    tools = create_all_tools(pktgen_host="192.168.1.100", pktgen_port=22022)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yaml

from pktgen_agent.compiler.compile import CompileError, SkillCompiler
from pktgen_agent.client import PktgenClient, PktgenConnectionError, execute_lua

logger = logging.getLogger(__name__)

# ── Paths ──

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_SKILLS_DIR = _PROJECT_ROOT / "dsl" / "skills"
_LUA_SCRIPTS_DIR = _PROJECT_ROOT / "lua_scripts"

# ── Lua script persistence ──


def _save_lua_script(skill_name: str, lua_code: str, mode: str) -> Path:
    """Save compiled Lua code to lua_scripts/ for debugging.

    Returns the path to the saved file.
    """
    _LUA_SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{skill_name}.lua"
    path = _LUA_SCRIPTS_DIR / filename
    path.write_text(lua_code, encoding="utf-8")
    logger.info("Lua script saved: %s (%s, %d bytes)", path, mode, len(lua_code))
    return path

# ── LangChain V1.0 imports ──

try:
    from langchain.tools import tool as lc_tool  # V1.0 @tool decorator
    from pydantic import BaseModel, Field, create_model
    HAS_LANGCHAIN = True
except ImportError:
    HAS_LANGCHAIN = False

# ── Type mapping ──

PYTHON_TYPE_MAP: dict[str, type] = {
    "string": str,
    "integer": int,
    "float": float,
    "boolean": bool,
    "enum": str,
    "mac_address": str,
    "ip_address": str,
    "portlist": str,
    "table": list,
}

# ── Compiler (module-level, lightweight) ──

compiler = SkillCompiler()


def compile_skill_lua(skill_name: str, params: dict[str, Any]) -> str:
    """Compile a skill to Lua. Raises CompileError on validation failure."""
    return compiler.compile(skill_name, params)


# ── Execution functions ──


def execute_skill_dry_run(
    skill_name: str, params: dict[str, Any]
) -> dict[str, Any]:
    """Compile skill and return Lua without executing against live Pktgen."""
    lua_code = compiler.compile(skill_name, params)
    _save_lua_script(skill_name, lua_code, "dry_run")
    logger.debug("Dry-run compiled skill=%s params=%s", skill_name, params)
    return {
        "success": True,
        "skill": skill_name,
        "params": params,
        "lua_code": lua_code,
        "mode": "dry_run",
    }


def execute_skill_live(
    skill_name: str,
    params: dict[str, Any],
    host: str = "localhost",
    port: int = 22022,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Compile skill and execute against a running Pktgen instance via TCP."""
    lua_code = compiler.compile(skill_name, params)
    try:
        with PktgenClient(host=host, port=port, timeout=timeout) as client:
            _save_lua_script(skill_name, lua_code, "live")
            response = client.execute(lua_code)
            logger.info("Live execution succeeded: skill=%s", skill_name)
        return {
            "success": True,
            "skill": skill_name,
            "params": params,
            "lua_code": lua_code,
            "response": response,
            "mode": "live",
        }
    except PktgenConnectionError as e:
        logger.error("Connection failed for skill=%s: %s", skill_name, e)
        return {
            "success": False,
            "skill": skill_name,
            "error": f"Connection failed: {e}",
            "lua_code": lua_code,
            "mode": "live",
        }
    except CompileError as e:
        logger.error("Compilation failed for skill=%s: %s", skill_name, e)
        return {
            "success": False,
            "skill": skill_name,
            "error": str(e),
            "mode": "live",
        }
    except Exception as e:
        logger.exception("Unexpected error executing skill=%s", skill_name)
        return {
            "success": False,
            "skill": skill_name,
            "error": f"Unexpected error: {e}",
            "lua_code": lua_code,
            "mode": "live",
        }


# ── Tool Factory ──


def _load_skill_meta(skill_name: str) -> dict:
    """Load a skill YAML and extract metadata for tool creation."""
    skill_path = _SKILLS_DIR / f"{skill_name}.yaml"
    if not skill_path.exists():
        raise FileNotFoundError(f"Skill file not found: {skill_path}")
    with open(skill_path) as f:
        data = yaml.safe_load(f)
    return data.get("skill", data)


def _build_pydantic_model(
    skill_name: str, params_def: list[dict]
) -> type[BaseModel] | None:
    """Dynamically create a Pydantic model from skill params definition."""
    if not HAS_LANGCHAIN:
        return None

    fields: dict[str, Any] = {}
    for p in params_def:
        pname = p["name"]
        ptype_str = p.get("type", "string")
        ptype = PYTHON_TYPE_MAP.get(ptype_str, str)
        description = p.get("description", "")
        required = p.get("required", False)
        default = p.get("default", None)

        if required:
            fields[pname] = (ptype, Field(description=description))
        else:
            fields[pname] = (
                ptype,
                Field(default=default, description=description),
            )

    model_name = (
        skill_name.replace("_", " ").title().replace(" ", "") + "Input"
    )
    if not fields:
        return None
    return create_model(model_name, **fields)


def create_skill_tool(
    skill_name: str,
    pktgen_host: str = "localhost",
    pktgen_port: int = 22022,
    dry_run: bool = False,
) -> Callable[..., dict[str, Any]]:
    """Create a LangChain tool for a given skill.

    Uses the V1.0 @tool decorator pattern when LangChain is available,
    falling back to a plain callable otherwise.

    Args:
        skill_name: Skill name (matches filename without .yaml).
        pktgen_host: Pktgen hostname for live execution.
        pktgen_port: Pktgen TCP port.
        dry_run: If True, only compile Lua without executing.

    Returns:
        A callable suitable for use as a LangChain tool.
    """
    meta = _load_skill_meta(skill_name)
    params_def = meta.get("params", [])
    description = meta.get("description", f"Execute {skill_name}")

    # Build rich description with parameter docs
    param_docs = "\n\nParameters:"
    for p in params_def:
        req = " (required)" if p.get("required") else ""
        default = f" [default: {p['default']}]" if "default" in p else ""
        param_docs += (
            f"\n  - {p['name']}: {p.get('type', 'string')}"
            f"{req}{default} — {p.get('description', '')}"
        )
    full_description = description + param_docs

    # ── Common executor ──
    def _execute(**kwargs: Any) -> dict[str, Any]:
        if dry_run:
            return execute_skill_dry_run(skill_name, kwargs)
        return execute_skill_live(
            skill_name, kwargs, host=pktgen_host, port=pktgen_port
        )

    if not HAS_LANGCHAIN:
        _execute.__name__ = skill_name
        _execute.__doc__ = full_description
        return _execute

    # ── LangChain V1.0: use @tool decorator pattern ──
    ArgsModel = _build_pydantic_model(skill_name, params_def)

    if ArgsModel is not None:
        @lc_tool(args_schema=ArgsModel)
        def tool_func(**kwargs: Any) -> str:
            """Execute the skill."""
            result = _execute(**kwargs)
            return json.dumps(result, indent=2)

        tool_func.name = skill_name  # type: ignore[attr-defined]
        tool_func.description = full_description  # type: ignore[attr-defined]
    else:
        # Skill has no parameters — simple tool
        @lc_tool
        def tool_func(**kwargs: Any) -> str:  # type: ignore[no-redef]
            """Execute the skill."""
            result = _execute(**kwargs)
            return json.dumps(result, indent=2)

        tool_func.name = skill_name  # type: ignore[attr-defined]
        tool_func.description = full_description  # type: ignore[attr-defined]

    return tool_func  # type: ignore[return-value]


def create_all_tools(
    pktgen_host: str = "localhost",
    pktgen_port: int = 22022,
    dry_run: bool = False,
) -> list[Callable[..., dict[str, Any]]]:
    """Create tools for all skills found in dsl/skills/.

    Args:
        pktgen_host: Pktgen hostname.
        pktgen_port: Pktgen TCP port.
        dry_run: If True, generate Lua without connecting to Pktgen.

    Returns:
        List of callables suitable for LangChain agents.
    """
    tools: list[Callable[..., dict[str, Any]]] = []
    if not _SKILLS_DIR.exists():
        logger.warning("Skills directory not found: %s", _SKILLS_DIR)
        return tools

    for skill_file in sorted(_SKILLS_DIR.glob("*.yaml")):
        skill_name = skill_file.stem
        tool = create_skill_tool(
            skill_name,
            pktgen_host=pktgen_host,
            pktgen_port=pktgen_port,
            dry_run=dry_run,
        )
        tools.append(tool)
        logger.debug("Created tool: %s", skill_name)

    logger.info("Created %d tools from %s", len(tools), _SKILLS_DIR)
    return tools
