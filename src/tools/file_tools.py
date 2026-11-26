"""General-purpose file tools: read_file / grep / write_file.

These give the agent a bounded "self-inspection" capability so it can verify
real source code (e.g. the TRex STL/ASTF client library) instead of trusting
the system prompt or skills, which may be stale.

Safety model:
  * read_file / grep are read-only and confined to the TRex client library
    source root — an operator-set path (get_trex_lib_dir()). That path lives
    on the experiment bed (e.g. /root/miniconda3/envs/trex311/lib/python3.11/
    site-packages), so it is NOT auto-detected or hardcoded here.
  * write_file is confined to a project-local sandbox (agent_scratch/), so it
    can never touch allowlist.json, source code, or config.
  * All three reject path traversal (``..`` / absolute escapes) via
    _resolve_under_root, mirroring skill_tool.py::_resolve_skill_path and
    trex/tools.py::_resolve_script_path.
"""
import re
from pathlib import Path
from typing import Any

from langchain.tools import tool

from src.trex.config import get_trex_lib_dir

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRATCH_DIR = _PROJECT_ROOT / "agent_scratch"

MAX_READ_CHARS = 12_000
MAX_WRITE_CHARS = 100_000
MAX_GREP_MATCHES = 50
MAX_GREP_CHARS = 4_000


def get_scratch_dir() -> Path:
    """Return the project-local sandbox dir for write_file (agent_scratch/)."""
    return _SCRATCH_DIR


def _resolve_under_root(path_str: str, root: Path) -> Path:
    """Resolve `path_str` against `root`, rejecting traversal / escapes.

    Accepts a root-relative path or an absolute path already inside the root;
    anything that resolves outside the root raises ValueError.
    """
    if not path_str or not isinstance(path_str, str):
        raise ValueError("path must be a non-empty string")
    root = root.resolve()
    candidate = (root / path_str).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError(f"path escapes the allowed root: {path_str!r}")
    return candidate


def _read_root() -> Path:
    """Return the resolved TRex library source root, or raise if unset."""
    root = (get_trex_lib_dir() or "").strip()
    if not root:
        raise ValueError(
            "TRex library source root is not set — set TREX_LIB_DIR "
            "(or trex.lib_dir in topology.yaml)."
        )
    return Path(root).resolve()


def _is_text_file(path: Path) -> bool:
    """Heuristic: skip binaries by sniffing a NUL byte in the first 8 KiB."""
    try:
        data = path.read_bytes()
    except OSError:
        return False
    return b"\x00" not in data[:8192]


@tool
def read_file(path: str) -> dict[str, Any]:
    """Read a text file from the TRex client library source root.

    Read-only, confined to the operator-configured TRex library source dir
    (TREX_LIB_DIR / trex.lib_dir). Use this to verify the real API signatures,
    units and defaults instead of trusting the (possibly stale) system prompt
    or skills.

    Args:
        path: File path relative to the TRex library root, e.g.
            "trex/stl/trex_stl_client.py"; an absolute path inside the root is
            also accepted.

    Returns:
        Dict with success, path, content (truncated if large), truncated.
    """
    try:
        root = _read_root()
    except ValueError as e:
        return {"success": False, "error": str(e)}

    try:
        target = _resolve_under_root(path, root)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    if not target.is_file():
        return {"success": False, "error": f"not a file: {path!r}"}

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {"success": False, "error": f"failed to read file: {e}"}

    truncated = len(content) > MAX_READ_CHARS
    if truncated:
        content = content[:MAX_READ_CHARS] + f"\n… (+{len(content) - MAX_READ_CHARS} chars)"
    return {
        "success": True,
        "path": str(target),
        "content": content,
        "truncated": truncated,
    }


@tool
def grep(pattern: str, path: str = ".") -> dict[str, Any]:
    """Search a regex pattern in text files under the TRex library source root.

    Read-only, confined to the TRex library source dir. Returns per-line
    matches as file/line/text so the agent can locate the real definitions.

    Args:
        pattern: Regular expression to search for (Python ``re`` syntax).
        path: Subdirectory or file under the root (default "." = whole root).

    Returns:
        Dict with success, pattern, matches: [{file, line, text}], match_count,
        truncated.
    """
    try:
        root = _read_root()
    except ValueError as e:
        return {"success": False, "error": str(e)}

    try:
        target = _resolve_under_root(path, root)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    try:
        regex = re.compile(pattern)
    except re.error as e:
        return {"success": False, "error": f"invalid regex: {e}"}

    files = [target] if target.is_file() else sorted(target.rglob("*"))

    matches: list[dict[str, Any]] = []
    total_chars = 0
    truncated = False
    for fp in files:
        if truncated:
            break
        try:
            real = fp.resolve()
        except OSError:
            continue
        # Skip symlinks that point outside the root, and non-files.
        if not real.is_relative_to(root) or not real.is_file():
            continue
        if not _is_text_file(real):
            continue
        try:
            lines = real.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue

        rel = real.relative_to(root)
        for lineno, line in enumerate(lines, 1):
            if not regex.search(line):
                continue
            if len(matches) >= MAX_GREP_MATCHES or total_chars > MAX_GREP_CHARS:
                truncated = True
                break
            matches.append({"file": str(rel), "line": lineno, "text": line})
            total_chars += len(str(rel)) + len(line) + 16

    return {
        "success": True,
        "pattern": pattern,
        "matches": matches,
        "match_count": len(matches),
        "truncated": truncated,
    }


@tool
def write_file(path: str, content: str) -> dict[str, Any]:
    """Write a text file into the agent_scratch/ sandbox directory.

    Confined to agent_scratch/ (project-local). Use for experiment notes or
    drafts; it cannot touch allowlist.json, source code, or config.

    Args:
        path: Relative path under agent_scratch/, e.g. "notes/verify_stl.md".
        content: Text content to write.

    Returns:
        Dict with success and path.
    """
    if len(content) > MAX_WRITE_CHARS:
        return {"success": False, "error": f"content exceeds {MAX_WRITE_CHARS} chars"}

    try:
        target = _resolve_under_root(path, get_scratch_dir())
    except ValueError as e:
        return {"success": False, "error": str(e)}

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except (OSError, ValueError) as e:
        return {"success": False, "error": f"failed to write file: {e}"}

    return {"success": True, "path": str(target)}


FILE_TOOLS = [read_file, grep, write_file]
