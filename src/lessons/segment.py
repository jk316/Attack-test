"""Associate a run with its agent-log conversation segment.

``src/main.py`` writes ``[RUN START] <run_id>`` / ``[RUN END] <run_id>`` marker
lines into the daily agent log; this module slices the text between them. When
markers are absent (legacy logs) or unpaired, it returns ``None`` so callers
degrade gracefully instead of misattributing another run's conversation
(spec 010 FR-006).
"""

from __future__ import annotations

from pathlib import Path

_RUN_START = "[RUN START] "
_RUN_END = "[RUN END] "


def extract_run_segment(run_id: str, text: str) -> str | None:
    """Return the text between ``[RUN START] {run_id}`` and ``[RUN END] {run_id}``.

    Returns ``None`` when the start marker is missing or has no matching end
    marker (never returns a fragment spanning another run).
    """
    start_marker = f"{_RUN_START}{run_id}"
    end_marker = f"{_RUN_END}{run_id}"

    start_idx = text.find(start_marker)
    if start_idx < 0:
        return None
    end_idx = text.find(end_marker, start_idx + len(start_marker))
    if end_idx < 0:
        return None
    return text[start_idx + len(start_marker):end_idx].strip()


def find_run_segment(run_id: str, data_dir: str | Path) -> str | None:
    """Locate the run's daily log by its embedded date and extract its segment.

    ``run_id`` format is ``YYYYmmddTHHMMSS-<hex6>``; the first 8 chars give the
    date (``YYYYmmdd``), mapped to ``agent-YYYY-MM-DD.log``. Returns ``None`` if
    the file is missing or the segment cannot be extracted.
    """
    if not isinstance(run_id, str) or len(run_id) < 8:
        return None
    ymd = run_id[:8]
    if not ymd.isdigit():
        return None
    date = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"

    log_path = Path(data_dir) / f"agent-{date}.log"
    if not log_path.exists():
        return None
    return extract_run_segment(run_id, log_path.read_text(encoding="utf-8"))
