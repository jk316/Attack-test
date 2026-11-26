#!/usr/bin/env python3
"""Generate experience-lesson documents (``lessons/{run_id}.md``) from logs.

Reads ``data/experiment.jsonl``, groups rows by ``run_id``, and for each run
not yet summarized writes a Markdown lesson (rule-based stats + optional
DeepSeek narrative). Idempotent: an existing ``lessons/{run_id}.md`` is skipped
unless ``--force`` is given.

Usage:
    uv run python scripts/generate_lessons.py               # all unsummarized runs
    uv run python scripts/generate_lessons.py --list        # print pending run_ids
    uv run python scripts/generate_lessons.py --latest      # only the newest run
    uv run python scripts/generate_lessons.py --run-id ID   # a specific run
    uv run python scripts/generate_lessons.py --no-llm      # rule-only, no LLM
    uv run python scripts/generate_lessons.py --force       # rewrite existing
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from src.lessons.extract import build_narrative, llm_client_from_env
from src.lessons.records import load_runs
from src.lessons.render import render_lesson
from src.lessons.segment import find_run_segment
from src.lessons.stats import summarize_run


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="从实验日志提炼经验教训，输出 lessons/{run_id}.md"
    )
    parser.add_argument("--log-path", default="data/experiment.jsonl",
                        help="输入 JSONL（默认 data/experiment.jsonl）")
    parser.add_argument("--data-dir", default="data/",
                        help="agent 每日日志所在目录（默认 data/）")
    parser.add_argument("--lessons-dir", default="lessons/",
                        help="输出目录（默认 lessons/，自动创建）")
    parser.add_argument("--run-id", default=None, help="仅处理指定 run_id")
    parser.add_argument("--latest", action="store_true", help="仅处理时间戳最新的 run")
    parser.add_argument("--force", action="store_true", help="重写已存在的 lessons 文件")
    parser.add_argument("--no-llm", action="store_true", help="强制规则要点，不发起 LLM 请求")
    parser.add_argument("--list", action="store_true", help="只打印待总结 run_id，不改文件")
    return parser.parse_args()


def _lesson_path(run_id: str, lessons_dir: str) -> Path:
    return Path(lessons_dir) / f"{run_id}.md"


def main() -> None:
    args = parse_args()

    log_path = Path(args.log_path)
    if not log_path.exists() or log_path.stat().st_size == 0:
        print(f"错误：日志文件缺失或为空: {log_path}", file=sys.stderr)
        sys.exit(1)

    result = load_runs(log_path)
    runs = list(result.runs)

    if args.list:
        pending = [
            run.run_id
            for run in runs
            if not _lesson_path(run.run_id, args.lessons_dir).exists()
        ]
        for run_id in pending:
            print(run_id)
        return

    if args.run_id:
        runs = [run for run in runs if run.run_id == args.run_id]
        if not runs:
            print(f"未找到 run_id={args.run_id}", file=sys.stderr)
            sys.exit(1)
    elif args.latest:
        if not runs:
            print("没有可处理的 run。", file=sys.stderr)
            sys.exit(1)
        runs = [runs[-1]]

    targets = [
        run
        for run in runs
        if args.force or not _lesson_path(run.run_id, args.lessons_dir).exists()
    ]
    if not targets:
        print("所有 run 均已总结（--force 可重写）。")
        return

    lessons_dir = Path(args.lessons_dir)
    lessons_dir.mkdir(parents=True, exist_ok=True)

    client = None if args.no_llm else llm_client_from_env()

    for run in targets:
        stats = summarize_run(run.rows)
        segment_text = find_run_segment(run.run_id, args.data_dir)
        lessons_text, suggestions_text, used_llm = build_narrative(
            stats, segment_text, client
        )
        doc = render_lesson(
            run.run_id, run, stats, (lessons_text, suggestions_text), used_llm
        )
        out_path = _lesson_path(run.run_id, args.lessons_dir)
        out_path.write_text(doc, encoding="utf-8")
        print(f"已生成: {out_path}")


if __name__ == "__main__":
    main()
