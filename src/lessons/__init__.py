"""Lessons pipeline: distill experience lessons from experiment logs.

Reads ``data/experiment.jsonl`` (grouped by ``run_id``), computes deterministic
rule-based statistics, optionally enriches them with a DeepSeek narrative (and
the run's agent-log segment), and renders ``lessons/{run_id}.md``.
"""

from src.lessons.records import RUN_ID_RE, LoadResult, Run, load_runs
from src.lessons.stats import IterationObservation, RunStats, summarize_run

__all__ = [
    "RUN_ID_RE",
    "LoadResult",
    "Run",
    "load_runs",
    "IterationObservation",
    "RunStats",
    "summarize_run",
]
