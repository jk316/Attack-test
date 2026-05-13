"""Log Tool - Writes experiment results to JSONL file"""
import json
import os
from datetime import datetime, timezone
from typing import Dict, Any


def log_tool(log_path: str, entry: Dict[str, Any]) -> Dict[str, Any]:
    """
    Append an experiment entry as a JSONL line to a log file.

    Args:
        log_path: Path to the JSONL file (created if it doesn't exist).
        entry: Dict with keys: params, rtt, loss, and optional iteration.

    Returns:
        Dict with success status and optional error message.
    """
    # Verify the parent directory exists
    parent = os.path.dirname(os.path.abspath(log_path))
    if parent and not os.path.isdir(parent):
        return {"success": False, "error": f"Directory does not exist: {parent}"}

    # Add timestamp
    record = dict(entry)
    record["timestamp"] = datetime.now(timezone.utc).isoformat()

    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python log_tool.py <log_path>")
        sys.exit(1)
    result = log_tool(
        sys.argv[1],
        {"params": {"pps": 10}, "rtt": 1.0, "loss": 0.0}
    )
    print(json.dumps(result, indent=2))
