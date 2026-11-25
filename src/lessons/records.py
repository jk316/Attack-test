"""Read ``experiment.jsonl`` and group rows into runs keyed by ``run_id``.

Only rows whose ``run_id`` matches the real format produced by
``generate_run_id()`` (``YYYYmmddTHHMMSS-<hex6>``) are kept; ``unknown`` and
legacy rows are skipped and counted.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# run_id format produced by src/tools/log_tool.generate_run_id()
RUN_ID_RE = re.compile(r"^\d{8}T\d{6}-[0-9a-f]{6}$")


@dataclass(frozen=True)
class Run:
    """One experiment run: all its jsonl rows plus derived metadata."""

    run_id: str
    rows: tuple[dict, ...]
    target_ip: str | None
    start_ts: str | None
    end_ts: str | None

    @property
    def iterations(self) -> int:
        return len(self.rows)


@dataclass(frozen=True)
class LoadResult:
    """Result of :func:`load_runs`, including skipped/bad line counts."""

    runs: tuple[Run, ...]
    total_lines: int
    bad_lines: int
    skipped_rows: int


def _sort_key(row: dict) -> tuple[int, Any]:
    """Order rows within a run by iteration (non-int iterations go last)."""
    iteration = row.get("iteration")
    if isinstance(iteration, int):
        return (0, iteration)
    return (1, 0)


def _build_run(run_id: str, rows: list[dict]) -> Run:
    target_ip: str | None = None
    for row in rows:
        params = row.get("params")
        if isinstance(params, dict) and params.get("target_ip"):
            target_ip = params["target_ip"]
            break

    timestamps = [
        row.get("timestamp")
        for row in rows
        if isinstance(row.get("timestamp"), str)
    ]
    start_ts = min(timestamps) if timestamps else None
    end_ts = max(timestamps) if timestamps else None
    return Run(run_id=run_id, rows=tuple(rows), target_ip=target_ip,
               start_ts=start_ts, end_ts=end_ts)


def load_runs(log_path: str | Path) -> LoadResult:
    """Parse ``log_path``, group valid-run_id rows into chronological runs.

    Blank lines are ignored silently; unparseable non-empty lines are counted
    in ``bad_lines``; valid-JSON rows with an invalid/unknown ``run_id`` are
    counted in ``skipped_rows``. Rows within a run are sorted by iteration and
    runs are sorted by ``run_id`` (its embedded timestamp sorts chronologically).
    """
    path = Path(log_path)
    rows_by_id: dict[str, list[dict]] = {}
    order: list[str] = []
    total_lines = 0
    bad_lines = 0
    skipped_rows = 0

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        total_lines += 1
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            bad_lines += 1
            continue
        if not isinstance(row, dict):
            bad_lines += 1
            continue

        run_id = row.get("run_id")
        if not isinstance(run_id, str) or not RUN_ID_RE.match(run_id):
            skipped_rows += 1
            continue

        if run_id not in rows_by_id:
            rows_by_id[run_id] = []
            order.append(run_id)
        rows_by_id[run_id].append(row)

    runs = [
        _build_run(run_id, sorted(rows_by_id[run_id], key=_sort_key))
        for run_id in order
    ]
    runs.sort(key=lambda run: run.run_id)

    return LoadResult(
        runs=tuple(runs),
        total_lines=total_lines,
        bad_lines=bad_lines,
        skipped_rows=skipped_rows,
    )
