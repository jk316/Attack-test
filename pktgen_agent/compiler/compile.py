"""
Pktgen Skill Compiler
Reads a skill YAML + user params → resolves topology/params → emits Lua code.

Input:  skill_name="udp_flood", params={rate: 80, pktSize: 512}
Output: Complete Lua script string ready for pktgen execution.

Grounded in:
  - dsl/schema.yaml    (API whitelist, enums, key validation)
  - dsl/mapping.yaml   (step→Lua compilation rules)
  - dsl/skills/*.yaml  (skill templates)
  - topology.yaml      (physical port mapping)
  - knowledge/         (reference — used for cross-checking)
"""

from __future__ import annotations

import re
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional

# Paths relative to project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DSL_DIR = _PROJECT_ROOT / "dsl"
_SKILLS_DIR = _DSL_DIR / "skills"
_SCHEMA_PATH = _DSL_DIR / "schema.yaml"
_TOPOLOGY_PATH = _PROJECT_ROOT / "topology.yaml"


class CompileError(Exception):
    """Raised when compilation fails due to validation or resolution errors."""

    def __init__(self, message: str, skill_name: str | None = None,
                 step_index: int | None = None, param_name: str | None = None):
        self.skill_name = skill_name
        self.step_index = step_index
        self.param_name = param_name
        super().__init__(message)


class SkillCompiler:
    """
    Compiles a skill file + user parameters → executable Lua code.

    Usage:
        compiler = SkillCompiler()
        lua = compiler.compile("udp_flood", {"rate": 80, "pktSize": 512})
    """

    def __init__(
        self,
        topology_path: Path | None = None,
        schema_path: Path | None = None,
        skills_dir: Path | None = None,
    ):
        self._topology_path = topology_path or _TOPOLOGY_PATH
        self._schema_path = schema_path or _SCHEMA_PATH
        self._skills_dir = skills_dir or _SKILLS_DIR
        self._topology: dict | None = None
        self._schema: dict | None = None
        self._valid_apis: set | None = None

    @property
    def topology(self) -> dict:
        if self._topology is None:
            with open(self._topology_path) as f:
                self._topology = yaml.safe_load(f)
        return self._topology

    @property
    def schema(self) -> dict:
        if self._schema is None:
            with open(self._schema_path) as f:
                self._schema = yaml.safe_load(f)
        return self._schema

    @property
    def valid_apis(self) -> set[str]:
        """Flattened set of all valid API function names from schema.yaml."""
        if self._valid_apis is None:
            apis: set[str] = set()
            for funcs in self.schema.get("valid_apis", {}).values():
                apis.update(funcs)
            apis.add("printf")
            apis.add("prints")
            self._valid_apis = apis
        return self._valid_apis

    def load_skill(self, skill_name: str) -> dict:
        """Load a skill YAML file by name."""
        skill_path = self._skills_dir / f"{skill_name}.yaml"
        if not skill_path.exists():
            raise CompileError(
                f"Skill not found: {skill_name} (expected at {skill_path})",
                skill_name=skill_name,
            )
        with open(skill_path) as f:
            data = yaml.safe_load(f)
        return data.get("skill", data)

    def validate_api(self, api_name: str) -> None:
        """Check that an API function exists in the schema whitelist."""
        if api_name not in self.valid_apis and not api_name.startswith("$"):
            raise CompileError(
                f"Unknown API function: '{api_name}'. Not found in dsl/schema.yaml valid_apis."
            )

    def validate_set_key(self, key: str) -> None:
        """Check that a pktgen.set() key is valid."""
        valid_keys = [k["key"] for k in self.schema.get("valid_set_keys", [])]
        if key not in valid_keys:
            raise CompileError(
                f"Unknown pktgen.set() key: '{key}'. Valid keys: {valid_keys}"
            )

    def resolve_topology(self, value: str) -> str:
        """Replace $topology.<name> with a Lua-quoted portlist literal.

        Handles two patterns:

        1. Bare reference — ``$topology.tx_port`` → ``"0"``
           (the entire arg is the topology key, needs quoting).

        2. Already-quoted reference — ``"$topology.monitor_port"`` →
           ``"all"`` (the surrounding quotes are part of the arg string;
           we replace the whole ``"$topology.xxx"`` token so we don't
           produce double-quoted garbage like ``""all""``).
        """
        portlist = self.topology  # cached after first access

        def _resolve(m: re.Match) -> str:
            name = m.group(1)
            if name not in portlist:
                raise CompileError(
                    f"Undefined topology reference: '{name}'. "
                    f"Available: {list(portlist.keys())}"
                )
            return self._to_lua_literal(portlist[name]["portlist"])

        # ── Step 1: replace already-quoted references ──
        # "$topology.<name>" → the surrounding " are consumed, _to_lua_literal re-adds them.
        value = re.sub(r'"\$topology\.(\w+)"', _resolve, value)

        # ── Step 2: replace bare references ──
        # $topology.<name> → _to_lua_literal adds quotes.
        return re.sub(r'\$topology\.(\w+)', _resolve, value)

    def resolve_params(
        self, value: str, user_params: dict, skill_params: list[dict]
    ) -> str:
        """Replace $params.<name> with user-supplied value or default."""
        pattern = r"\$params\.(\w+)"

        def replacer(match: re.Match) -> str:
            name = match.group(1)
            if name in user_params:
                return self._to_lua_literal(user_params[name])
            # Look up default from skill params definition
            for p in skill_params:
                if p.get("name") == name:
                    if "default" in p:
                        return self._to_lua_literal(p["default"])
                    raise CompileError(
                        f"Parameter '{name}' is required but not provided. "
                        f"Available params: {[p['name'] for p in skill_params]}"
                    )
            raise CompileError(f"Undefined parameter reference: '{name}'")

        return re.sub(pattern, replacer, value)

    def resolve_special(self, value: str, skill: dict, user_params: dict) -> str:
        """Resolve special references like $sequence_count, $range_api."""
        if "$sequence_count" in value:
            seq_param = user_params.get("sequences", [])
            value = value.replace("$sequence_count", str(len(seq_param)))
        return value

    def _to_lua_literal(self, value: Any) -> str:
        """Convert a Python value to its Lua literal representation.

        Escapes embedded double quotes to prevent Lua injection.
        """
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, str):
            # If it's a reference, don't modify
            if value.startswith("$"):
                return value
            # Escape embedded double quotes and wrap in quotes
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'
        if isinstance(value, (int, float)):
            return str(value)
        if value is None:
            return "nil"
        raise CompileError(
            f"Cannot convert value to Lua literal: {value!r} "
            f"(type: {type(value).__name__}). "
            f"This usually means the parameter value is malformed — check the input."
        )

    def compile_step(
        self, step: dict, user_params: dict, skill: dict
    ) -> list[str]:
        """Compile a single DSL step into one or more Lua lines."""
        lines: list[str] = []

        # Skip steps marked as skip or without an API (comment-only steps)
        if step.get("skip") or not step.get("api"):
            return lines

        # Skip steps with unmet conditions
        if "condition" in step and step["condition"]:
            condition = self.resolve_topology(step["condition"])
            condition = self.resolve_params(
                condition, user_params, skill.get("params", [])
            )
            lines.append(f"if ( {condition} ) then")

        api = step.get("api", "")
        args = step.get("args", [])
        assign_to = step.get("assign_to", None)
        table_data = step.get("table_data", None)
        table_name = step.get("table_name", "tbl")

        # Resolve API (e.g., $range_api → pktgen.range.dst_ip)
        api = self.resolve_params(api, user_params, skill.get("params", []))
        api = self.resolve_topology(api)

        # Validate API exists (skip for special refs resolved at runtime)
        if not api.startswith("$") and api not in ("printf", "prints"):
            self.validate_api(api)

        # Resolve args
        resolved_args: list[str] = []
        for arg in args:
            arg_str = str(arg)
            arg_str = self.resolve_topology(arg_str)
            arg_str = self.resolve_params(
                arg_str, user_params, skill.get("params", [])
            )
            arg_str = self.resolve_special(arg_str, skill, user_params)
            resolved_args.append(arg_str)

        # Validate pktgen.set() keys
        if api == "pktgen.set" and len(resolved_args) >= 2:
            key = resolved_args[1].strip('"')
            self.validate_set_key(key)

        # ── Emit Lua based on step type ──

        # seqTable call — emit table literal first
        if api == "pktgen.seqTable" and table_data:
            lines.append(f"local {table_name} = {{")
            if isinstance(table_data, str) and table_data.startswith("$"):
                lines.append(f"  -- table data from {table_data}")
            elif isinstance(table_data, dict):
                for k, v in table_data.items():
                    lines.append(f'    ["{k}"] = {self._to_lua_literal(v)},')
            lines.append("};")
            lines.append(
                f"pktgen.seqTable({', '.join(resolved_args[:2])}, {table_name});"
            )
            return self._indent(lines, step)

        # Assignment call: local var = api(...)
        if assign_to:
            lines.append(f"local {assign_to} = {api}({', '.join(resolved_args)});")
            return self._indent(lines, step)

        # No-args call
        if not resolved_args:
            lines.append(f"{api}();")
            return self._indent(lines, step)

        # Direct call
        lines.append(f"{api}({', '.join(resolved_args)});")

        return self._indent(lines, step)

    def _parse_phase(self, phase: list | dict) -> tuple[dict | None, list[dict]]:
        """Parse a phase definition, supporting both list and dict formats.

        List format (backward compatible)::

            plan:
              - api: ...
              - api: ...

        Dict format (with phase-level repeat)::

            plan:
              repeat: {count: "$params.iterations", interval_ms: 1000}
              steps:
                - api: ...
                - api: ...

        Returns:
            (phase_repeat or None, list of step dicts).
        """
        if isinstance(phase, dict):
            return phase.get("repeat"), phase.get("steps", [])
        return None, phase if isinstance(phase, list) else []

    def _indent(self, lines: list[str], step: dict) -> list[str]:
        """Apply indentation if inside a condition block."""
        if "condition" in step:
            return [f"    {l}" for l in lines] + ["end"]
        return lines

    def compile_phase(
        self,
        steps: list[dict],
        user_params: dict,
        skill: dict,
        phase_name: str,
        phase_repeat: dict | None = None,
    ) -> list[str]:
        """Compile a list of steps (setup/plan/teardown).

        Args:
            steps: List of step dicts.
            user_params: User-supplied parameter values.
            skill: Full skill dict (for param defaults).
            phase_name: Phase label for comments.
            phase_repeat: Optional repeat config for the entire phase
                          (``{"count": 10, "interval_ms": 1000}``).
                          When set, ALL steps in the phase are wrapped in
                          a single ``for`` loop so monitoring/repeated
                          operations collect fresh data each iteration.
        """
        lua_lines: list[str] = []
        if not steps:
            return lua_lines

        lua_lines.append(f"-- [{phase_name}]")

        # ── Phase-level repeat ──
        if phase_repeat:
            count = phase_repeat.get("count", 1)
            interval = phase_repeat.get("interval_ms", 0)

            count_str = str(count)
            count_str = self.resolve_params(
                count_str, user_params, skill.get("params", [])
            )
            try:
                count = int(count_str)
            except ValueError:
                count = 1

            lua_lines.append(f"for i = 1, {count} do")

        for step in steps:
            # Handle step-level repeat
            if "repeat" in step:
                repeat_cfg = step.get("repeat", {})
                count = repeat_cfg.get("count", 1)
                interval = repeat_cfg.get("interval_ms", 0)

                # Resolve count if it's a param ref
                count_str = str(count)
                count_str = self.resolve_params(
                    count_str, user_params, skill.get("params", [])
                )
                try:
                    count = int(count_str)
                except ValueError:
                    count = 1

                lua_lines.append(f"for i = 1, {count} do")
                inner = self.compile_step(step, user_params, skill)
                lua_lines.extend([f"    {l}" for l in inner])
                if interval:
                    interval_str = self.resolve_params(
                        str(interval), user_params, skill.get("params", [])
                    )
                    lua_lines.append(f"    pktgen.delay({interval_str});")
                lua_lines.append("end")
            else:
                inner = self.compile_step(step, user_params, skill)
                if phase_repeat:
                    lua_lines.extend([f"    {l}" for l in inner])
                else:
                    lua_lines.extend(inner)

        # Close phase-level repeat
        if phase_repeat:
            if phase_repeat.get("interval_ms", 0):
                interval_str = self.resolve_params(
                    str(phase_repeat.get("interval_ms", 0)),
                    user_params,
                    skill.get("params", []),
                )
                lua_lines.append(f"    pktgen.delay({interval_str});")
            lua_lines.append("end")

        return lua_lines

    def compile(
        self, skill_name: str, user_params: dict | None = None
    ) -> str:
        """
        Compile a skill into executable Lua code.

        Args:
            skill_name: Name of the skill (matches filename without .yaml).
            user_params: User-supplied parameter values.

        Returns:
            Complete Lua script string.

        Raises:
            CompileError: On validation failure or resolution error.
        """
        if user_params is None:
            user_params = {}

        skill = self.load_skill(skill_name)
        skill_params = skill.get("params", [])

        # ── Phase 1: Validate user params against skill schema ──
        for p in skill_params:
            pname = p["name"]
            if p.get("required", False) and pname not in user_params:
                raise CompileError(
                    f"Required parameter '{pname}' not provided for skill '{skill_name}'",
                    skill_name=skill_name,
                    param_name=pname,
                )

            if pname in user_params:
                val = user_params[pname]
                ptype = p.get("type", "string")
                constraints = p.get("constraints", {})

                # Type check
                if ptype == "boolean" and not isinstance(val, bool):
                    raise CompileError(
                        f"Parameter '{pname}' must be boolean (true/false), "
                        f"got {type(val).__name__}: {val!r}",
                        skill_name=skill_name,
                        param_name=pname,
                    )
                if ptype == "integer" and not isinstance(val, int):
                    raise CompileError(
                        f"Parameter '{pname}' must be integer, "
                        f"got {type(val).__name__}",
                        skill_name=skill_name,
                        param_name=pname,
                    )
                if ptype == "float" and not isinstance(val, (int, float)):
                    raise CompileError(
                        f"Parameter '{pname}' must be number, "
                        f"got {type(val).__name__}",
                        skill_name=skill_name,
                        param_name=pname,
                    )

                # Range check
                if "min" in constraints and val < constraints["min"]:
                    raise CompileError(
                        f"Parameter '{pname}'={val} below minimum {constraints['min']}",
                        skill_name=skill_name,
                        param_name=pname,
                    )
                if "max" in constraints and val > constraints["max"]:
                    raise CompileError(
                        f"Parameter '{pname}'={val} above maximum {constraints['max']}",
                        skill_name=skill_name,
                        param_name=pname,
                    )

                # Enum check — supports both constraints.enum and top-level enum
                valid_enum = (
                    constraints["enum"] if "enum" in constraints
                    else p.get("enum")
                )
                if valid_enum and val not in valid_enum:
                    raise CompileError(
                        f"Parameter '{pname}'='{val}' not in valid values: "
                        f"{valid_enum}",
                        skill_name=skill_name,
                        param_name=pname,
                    )

        # ── Phase 2: Emit Lua ──
        lua: list[str] = []
        # Prologue
        lua.append(
            'package.path = package.path ..";?.lua;test/?.lua;app/?.lua;"'
        )
        lua.append("")
        lua.append('require "Pktgen"')
        lua.append("")

        # Setup
        setup_phase = skill.get("setup", [])
        setup_repeat, setup_steps = self._parse_phase(setup_phase)
        lua.extend(
            self.compile_phase(setup_steps, user_params, skill, "setup", setup_repeat)
        )
        if setup_steps:
            lua.append("")

        # Plan
        plan_phase = skill.get("plan", [])
        plan_repeat, plan_steps = self._parse_phase(plan_phase)
        lua.extend(
            self.compile_phase(plan_steps, user_params, skill, "plan", plan_repeat)
        )
        if plan_steps:
            lua.append("")

        # Teardown
        teardown_phase = skill.get("teardown", [])
        teardown_repeat, teardown_steps = self._parse_phase(teardown_phase)
        lua.extend(
            self.compile_phase(
                teardown_steps, user_params, skill, "teardown", teardown_repeat
            )
        )

        return "\n".join(lua) + "\n"


# ── Convenience function ──


def compile_skill(skill_name: str, params: dict | None = None) -> str:
    """Compile a skill to Lua. Raises CompileError on validation failure."""
    compiler = SkillCompiler()
    return compiler.compile(skill_name, params)
