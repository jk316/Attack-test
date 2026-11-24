"""On-demand skill loader: load_skill / list_skills.

Skills are static markdown files under <project_root>/skills/ that carry
domain-specific "经验教训" (correct usage, pitfalls, hard-won environment
facts). The agent loads them on demand instead of carrying them in the system
prompt, so an experiment that never touches a domain never pays its context
cost. This is the lightweight knowledge base; see docs/knowledge-base.md for
the larger (structured + vector + reflection) vision.
"""
import re
from pathlib import Path
from typing import Any

from langchain.tools import tool

# Project root = src/tools/skill_tool.py -> ../../.. -> repo root
SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / "skills"
_SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
MAX_SKILL_CHARS = 12_000


def _resolve_skill_path(name: str) -> Path:
    """Map a skill name to its markdown file, rejecting path traversal."""
    if not name or not isinstance(name, str) or not _SKILL_NAME_RE.match(name):
        raise ValueError(
            f"invalid skill name (lowercase alnum + hyphen only): {name!r}"
        )
    return SKILLS_DIR / f"{name}.md"


@tool
def load_skill(name: str) -> dict[str, Any]:
    """Load a skill's full content into context on demand.

    Skills are static markdown files carrying domain knowledge / hard-won
    lessons (correct API usage, pitfalls, environment facts). Call this BEFORE
    using a domain's tools — e.g. `load_skill("trex-astf")` before generating
    TRex scripts. Use `list_skills()` first to see what is available.

    Args:
        name: Skill name (lowercase letters/digits/hyphens), e.g. "trex-astf".

    Returns:
        Dict with success, skill, content (possibly truncated), or
        success=False + error.
    """
    try:
        path = _resolve_skill_path(name)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    if not path.exists():
        return {
            "success": False,
            "error": f"skill not found: {name!r} (see list_skills)",
        }

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as e:
        return {"success": False, "error": f"failed to read skill: {e}"}

    truncated = len(content) > MAX_SKILL_CHARS
    if truncated:
        content = (
            content[:MAX_SKILL_CHARS] + f"\n… (+{len(content) - MAX_SKILL_CHARS} chars)"
        )
    return {"success": True, "skill": name, "content": content, "truncated": truncated}


def _first_title(text: str) -> str:
    """Extract the first heading (or first non-empty line) as a one-line title."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    return ""


@tool
def list_skills() -> dict[str, Any]:
    """List available skills (name + title) in the on-demand knowledge base.

    Returns:
        Dict with success and skills: [{name, title}], or success=False + error.
    """
    try:
        files = sorted(SKILLS_DIR.glob("*.md"))
    except OSError as e:
        return {"success": False, "error": f"failed to list skills: {e}"}

    skills = []
    for path in files:
        if not _SKILL_NAME_RE.match(path.stem):
            continue
        try:
            title = _first_title(path.read_text(encoding="utf-8"))
        except OSError:
            title = ""
        skills.append({"name": path.stem, "title": title})
    return {"success": True, "skills": skills}


SKILL_TOOLS = [load_skill, list_skills]
