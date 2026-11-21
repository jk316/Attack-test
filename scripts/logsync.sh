#!/usr/bin/env bash
# =============================================================================
# logsync.sh —— 把服务器上的实验日志/数据一键提交并推送到远程
#
# 用法（在服务器上，任意目录执行）:
#   bash scripts/logsync.sh                  # 提交信息自动带时间戳
#   bash scripts/logsync.sh "TRex 满线速 SYN 测试"   # 自定义提交信息
#
# 流程: pull --rebase → add data/ + experiment.json → 无变更则跳过 → commit → push
# 说明:
#   - 只暂存 data/（日志、实验数据）与 experiment.json（运行配置），
#     不碰其他任何文件；
#   - 若工作区还有这两者之外的未提交改动，脚本会提醒但不会代提交。
# =============================================================================
set -uo pipefail

cd "$(git rev-parse --show-toplevel)" || { echo "❌ 不在 git 仓库内"; exit 1; }

# ── 1. 先同步远程，避免 push 冲突 ──
echo "── git pull --rebase ──"
if ! git pull --rebase; then
  echo "❌ pull 失败。可能有未提交改动挡住了 rebase，请先处理（git status 查看），再重跑。"
  exit 1
fi

# ── 2. 检查工作区是否有其他未提交改动（data/ 与 experiment.json 之外的）──
OTHER="$(git status --porcelain | grep -vE '^.. data/' | grep -vE '^.. experiment\.json' || true)"
if [ -n "$OTHER" ]; then
  echo "⚠️  存在本次不会提交的改动："
  echo "$OTHER"
  echo "   （本脚本只提交 data/ 与 experiment.json，请自行处理上面这些文件）"
fi

# ── 3. 暂存日志与运行配置 ──
git add data/ experiment.json

# ── 4. 没有变更就直接结束 ──
if git diff --cached --quiet; then
  echo "✅ 没有新的日志/配置变更，无需提交。"
  exit 0
fi

echo "── 本次将提交的内容 ──"
git diff --cached --stat

# ── 5. 提交 ──
MSG="${1:-log auto $(date '+%Y-%m-%d %H:%M:%S')}"
git commit -m "$MSG"

# ── 6. 推送 ──
echo "── git push ──"
if git push; then
  echo "✅ 已推送：$MSG"
else
  echo "❌ push 失败（网络？）。提交已在本地，网络恢复后重跑本脚本即可（无变更时自动跳过）。"
  exit 1
fi
