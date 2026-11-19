#!/usr/bin/env bash
# Watchdog 特性验收工具。用法:
#   bash .dsh/verify-feature.sh <特性目录名>          # 勾选统计 + git log
#   bash .dsh/verify-feature.sh <特性目录名> --full   # 另跑全量测试
set -euo pipefail
FEAT="${1:?用法: verify-feature.sh <特性目录名> [--full]}"
DIR="specs/$FEAT"
[ -f "$DIR/tasks.md" ] || { echo "找不到 $DIR/tasks.md"; exit 1; }
T=$(grep -c '^\s*- \[[ xX]\] T' "$DIR/tasks.md" || true)
D=$(grep -c '^\s*- \[[xX]\] T' "$DIR/tasks.md" || true)
O=$((T-D))
echo "== [$FEAT] 勾选统计: 总 $T / 完成 $D / 未完成 $O =="
if [ "$O" -gt 0 ]; then
  echo "-- 未完成清单 --"
  grep '^\s*- \[ \] T' "$DIR/tasks.md" || true
fi
echo "-- git log（近 8 条）--"
git log --oneline -8
if [ "${2:-}" = "--full" ]; then
  echo "-- 全量测试 --"
  bash .dsh/run-tests.sh tests/ -q --tb=line 2>&1 | tail -15
fi
