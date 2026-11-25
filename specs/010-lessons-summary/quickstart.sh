#!/usr/bin/env bash
# One-click verification for the lessons-summary feature (spec 010).
#
# Runs: 场景0 环境检查 → 场景1 生成 → 场景2 幂等 → 场景3 --list.
# Uses a temp lessons dir (never pollutes the real lessons/) and --no-llm
# (no API key needed). Exit code 0 on all-green.
set -u

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

PASS=0
FAIL=0
DEMO="$(mktemp -d)"

step() { printf '\n=== %s ===\n' "$1"; }
ok()   { printf '✅ %s\n' "$1"; PASS=$((PASS + 1)); }
bad()  { printf '❌ %s\n' "$1"; FAIL=$((FAIL + 1)); }

step "场景0: 环境检查"
if uv run python -c "import src.lessons.records" >/dev/null 2>&1; then
  ok "src.lessons 可导入"
else
  bad "src.lessons 导入失败（先 uv sync --extra dev）"
fi

step "场景1: 生成 lessons（--no-llm，临时目录）"
if uv run python scripts/generate_lessons.py --no-llm --lessons-dir "$DEMO" >/dev/null 2>&1; then
  ok "生成成功"
else
  bad "生成失败"
fi
COUNT="$(ls -1 "$DEMO" 2>/dev/null | wc -l | tr -d ' ')"
if [ "$COUNT" -gt 0 ]; then
  ok "生成 $COUNT 个 lessons 文件"
else
  bad "生成 0 个文件"
fi

step "场景2: 幂等（二次运行 0 变更）"
BEFORE="$(find "$DEMO" -type f -exec md5sum {} \; | sort)"
uv run python scripts/generate_lessons.py --no-llm --lessons-dir "$DEMO" >/dev/null 2>&1
AFTER="$(find "$DEMO" -type f -exec md5sum {} \; | sort)"
if [ "$BEFORE" = "$AFTER" ]; then
  ok "二次运行无变更（幂等）"
else
  bad "二次运行产生变更"
fi

step "场景3: --list 只打印不改文件"
LIST="$(uv run python scripts/generate_lessons.py --list 2>/dev/null)"
if [ -n "$LIST" ]; then
  ok "--list 输出待总结 run_id"
else
  bad "--list 无输出（可能全部已总结，属正常）"
fi

rm -rf "$DEMO"

printf '\n============================================\n'
printf '通过: %d  失败: %d\n' "$PASS" "$FAIL"
printf '============================================\n'
[ "$FAIL" -eq 0 ]
