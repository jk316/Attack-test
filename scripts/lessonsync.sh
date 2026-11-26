#!/usr/bin/env bash
# =============================================================================
# lessonsync.sh —— 把服务器上生成的 lessons 经验教训一键提交并推送到远程
#
# 用法（在服务器上，任意目录执行）:
#   bash scripts/lessonsync.sh                 # 提交信息自动带时间戳
#   bash scripts/lessonsync.sh "TRex SYN 教训"  # 自定义提交信息
#   DRY_RUN=1 bash scripts/lessonsync.sh       # 只演示将执行的步骤，不做任何改动
#
# 流程: add lessons/ →（有变更才）commit → pull --rebase → push
# 为什么先 commit 再 pull：git rebase 要求工作区干净，而 generate_lessons.py
# 跑完后 lessons/*.md 必然有未提交改动，先提交才能执行 rebase。
#
# 说明:
#   - 只暂存 lessons/ 目录（含新增的 lessons/{run_id}.md），不碰其他文件；
#   - 若工作区还有 lessons/ 之外的未提交改动，脚本会提醒；那些改动可能
#     挡住 pull --rebase，请先自行处理；
#   - push 失败后重跑本脚本：lessons 无新变更时会自动继续推送未推送的提交。
# =============================================================================
set -uo pipefail

cd "$(git rev-parse --show-toplevel)" || { echo "❌ 不在 git 仓库内"; exit 1; }

DRY_RUN="${DRY_RUN:-0}"

# ── 1. 检查其他未提交改动（lessons/ 之外）─────────────────────────
OTHER="$(git status --porcelain | grep -vE '^.. lessons/' || true)"
if [ -n "$OTHER" ]; then
  echo "⚠️  存在本次不会提交的改动（可能挡住后面的 pull --rebase）："
  echo "$OTHER"
  echo "   （本脚本只提交 lessons/ 目录）"
fi

# ── 2. 暂存 lessons/ 目录 ─────────────────────────────────────────
if [ "$DRY_RUN" = "1" ]; then
  CHANGED="$(git diff -- lessons/ | grep -c . || true)"
  [ "$CHANGED" != "0" ] && CHANGED=1
else
  git add 'lessons/'
  if git diff --cached --quiet; then CHANGED=0; else CHANGED=1; fi
fi

UNPUSHED="$(git rev-list --count @{u}..HEAD 2>/dev/null || echo 0)"

if [ "$CHANGED" = "0" ] && [ "$UNPUSHED" = "0" ]; then
  echo "✅ 没有新的 lessons 变更，也没有未推送的提交。"
  exit 0
fi

# ── 3. 有变更先提交（让工作区干净，rebase 才能执行）────────────────
if [ "$CHANGED" = "1" ]; then
  if [ "$DRY_RUN" = "1" ]; then
    echo "── 本次将提交的内容（dry-run 预览）──"
    git diff --stat -- lessons/
  else
    echo "── 本次将提交的内容 ──"
    git diff --cached --stat
  fi
  MSG="${1:-lessons auto $(date '+%Y-%m-%d %H:%M:%S')}"
  if [ "$DRY_RUN" = "1" ]; then
    echo "[DRY_RUN] git commit -m \"$MSG\""
  else
    git commit -m "$MSG"
  fi
else
  echo "ℹ️  lessons 无新变更，但本地有 $UNPUSHED 个未推送提交，继续同步。"
fi

# ── 4. 同步远程（先提交后 rebase，工作区已干净）────────────────────
if [ "$DRY_RUN" = "1" ]; then
  echo "[DRY_RUN] git pull --rebase"
else
  echo "── git pull --rebase ──"
  if ! git pull --rebase; then
    echo "❌ pull --rebase 失败。通常是上面 ⚠️ 列出的其他未提交改动挡住了；"
    echo "   lessons 已安全提交到本地，处理完那些改动后重跑本脚本即可（会自动继续推送）。"
    exit 1
  fi
fi

# ── 5. 推送 ───────────────────────────────────────────────────────
if [ "$DRY_RUN" = "1" ]; then
  echo "[DRY_RUN] git push"
else
  echo "── git push ──"
  if git push; then
    echo "✅ 已推送：$MSG"
  else
    echo "❌ push 失败（网络？）。提交已在本地，网络恢复后重跑本脚本即可。"
    exit 1
  fi
fi
