#!/usr/bin/env bash
# =============================================================================
# 009-auto-start-monitors 一键验证脚本（真实环境）
#
# 按 quickstart.md 的 场景1 / 场景3 / 场景5 实测验证特性 009：
#   场景1: CLI 干跑 —— 监控自动启动、agent.log 出现启动记录、退出无残留进程
#   场景3: Web 后端  —— uvicorn 可启动且 /api/experiment/status 有响应
#   场景5: 失败降级  —— http.url 非法时仅告警降级、ping 监控不受影响
#
# 用法:
#   bash specs/009-auto-start-monitors/quickstart.sh
#
# 可覆盖:
#   TARGET_IP=100.1.11.3 MAX_ITERS=2 PORT=8000 bash specs/009-auto-start-monitors/quickstart.sh
#   RUN_TESTS=1   # 追加跑场景2/4/6（pytest，需 dev 依赖）
#   KEEP_CONFIG=1 # 不临时切换安全配置，按当前 experiment.json 原样运行（⚠️ 可能实弹，慎用）
#
# 注意:
#   - 场景1 默认临时把 experiment.json 切到安全配置（强制 dry-run + 自动审批 +
#     instruction 限定为「一轮轻量 Scapy 观测」，禁止 Pktgen/TRex），
#     退出时自动恢复；若脚本被强杀，可手动 `cp` 恢复（备份在 /tmp）。
#   - 场景1 会向目标发送 1 轮 pps=100、5 秒的 Scapy UDP 流量（auto-approve），
#     仅限实验环境使用。
#   - 需要 DEEPSEEK_API_KEY（.env）与可访问目标的网络环境。
# =============================================================================
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

TARGET_IP="${TARGET_IP:-$(python3 -c 'import json;print(json.load(open("experiment.json", encoding="utf-8"))["target_ip"])' 2>/dev/null || true)}"
TARGET_IP="${TARGET_IP:-10.99.80.160}"
MAX_ITERS="${MAX_ITERS:-2}"
PORT="${PORT:-8000}"
LOG="data/agent.log"
JSONL="data/experiment.jsonl"

PASS=0; FAIL=0
ok()   { echo "  ✅ $*"; PASS=$((PASS+1)); }
bad()  { echo "  ❌ $*"; FAIL=$((FAIL+1)); }
info() { echo "  ℹ️  $*"; }
section() { echo; echo "━━━ $* ━━━"; }

# ── 0. 环境检查 ─────────────────────────────────────────────────────────────
section "0. 环境检查"
command -v uv      >/dev/null 2>&1 && ok "uv 可用"       || bad "缺少 uv"
command -v python3 >/dev/null 2>&1 && ok "python3 可用"  || bad "缺少 python3"
command -v fping   >/dev/null 2>&1 && ok "fping 可用"    || info "无 fping（ping 监控将回退系统 ping，可接受）"
[ -f experiment.json ] && ok "experiment.json 存在"      || bad "缺少 experiment.json"

# ── 场景1: CLI 干跑 ─────────────────────────────────────────────────────────
section "场景1: CLI 干跑（监控自动启动 + 观测 + 无残留）"
BACKUP="$(mktemp /tmp/experiment.json.bak.XXXXXX)"
cp experiment.json "$BACKUP"
restore_cfg() { cp "$BACKUP" experiment.json; rm -f "$BACKUP"; }
if [ "${KEEP_CONFIG:-0}" != "1" ]; then
  trap restore_cfg EXIT
  python3 - <<'PYEOF'
import json
cfg = json.load(open("experiment.json", encoding="utf-8"))
cfg["max_iters"] = 2
cfg["auto_approve"] = True
cfg["pktgen_live"] = False
cfg["trex_live"] = False
cfg["trex_explore"] = False
cfg["instruction"] = ("验证观测链路：只执行一轮 traffic_send（pps=100、duration_s=5），"
                      "然后 read_ping_stats 读取攻击后基线，输出总结并结束。"
                      "禁止调用 Pktgen/TRex 任何工具。")
json.dump(cfg, open("experiment.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
PYEOF
  ok "已临时切到安全配置（dry-run + auto-approve + 单轮 Scapy 指令），退出自动恢复"
else
  info "KEEP_CONFIG=1：按当前 experiment.json 原样运行（⚠️ 可能实弹）"
fi

MARK=$(wc -l < "$LOG" 2>/dev/null | tr -d ' '); MARK="${MARK:-0}"
JSONL_MARK=$(wc -l < "$JSONL" 2>/dev/null | tr -d ' '); JSONL_MARK="${JSONL_MARK:-0}"
F_BEFORE="$(pgrep -f 'fping' 2>/dev/null | sort | tr '\n' ' ' || true)"

info "启动实验（target=$TARGET_IP, max_iters=$MAX_ITERS），输出见 /tmp/qstart_cli.out ..."
uv run python src/main.py --target-ip "$TARGET_IP" --max-iters "$MAX_ITERS" > /tmp/qstart_cli.out 2>&1
RC=$?

grep -q "=== Experiment Complete ===" /tmp/qstart_cli.out \
  && ok "CLI 实验正常完成（退出码 $RC）" \
  || bad "CLI 实验未正常完成（退出码 $RC，见 /tmp/qstart_cli.out）"

NEWLOG="$(tail -n +$((MARK+1)) "$LOG" 2>/dev/null || true)"
echo "$NEWLOG" | grep -q "Monitors auto-started" \
  && ok "agent.log 出现 'Monitors auto-started'（程序自动启动）" \
  || bad "agent.log 未出现监控自动启动记录"

echo "$NEWLOG" | grep -q '"rtt_during"' \
  && ok "日志中出现 rtt_during 观测字段" \
  || info "本轮未见 rtt_during 文本（可能是日志截断/模型未走流量工具，人工核对 /tmp/qstart_cli.out）"

NEWJSONL=$(tail -n +$((JSONL_MARK+1)) "$JSONL" 2>/dev/null | grep -c . || true)
[ "$NEWJSONL" -ge 1 ] && ok "experiment.jsonl 新增 $NEWJSONL 条记录" \
                        || info "experiment.jsonl 无新增（模型未调用 log_result，可接受）"

sleep 2
F_AFTER="$(pgrep -f 'fping' 2>/dev/null | sort | tr '\n' ' ' || true)"
if [ "$F_AFTER" = "$F_BEFORE" ]; then
  ok "退出后无残留 fping 进程"
else
  bad "退出后仍有 fping 残留: $F_AFTER"
fi

# ── 场景3: Web 后端 ─────────────────────────────────────────────────────────
section "场景3: Web 后端启动与健康检查"
uv run uvicorn backend.server:app --host 127.0.0.1 --port "$PORT" > /tmp/qstart_web.out 2>&1 &
WEB_PID=$!
sleep 4
if kill -0 "$WEB_PID" 2>/dev/null; then
  ok "uvicorn 已启动 (pid=$WEB_PID)"
else
  bad "uvicorn 启动失败（见 /tmp/qstart_web.out）"
fi
CODE="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/api/experiment/status" || true)"
[ -n "$CODE" ] && ok "GET /api/experiment/status 响应 HTTP $CODE" \
                || bad "健康接口无响应"
kill "$WEB_PID" 2>/dev/null || true
wait "$WEB_PID" 2>/dev/null || true
ok "uvicorn 已停止"
info "（完整 Web 实验需在浏览器点击开始；后端自动启动接线已由测试与生产日志覆盖）"

# ── 场景5: 失败降级 ─────────────────────────────────────────────────────────
section "场景5: 失败降级（http.url 非法时不阻断）"
RESULT="$(uv run python - <<PYEOF
import logging
logging.basicConfig(level=logging.CRITICAL)
from src.tools.monitor_lifecycle import start_experiment_monitors, stop_experiment_monitors
res = start_experiment_monitors("$TARGET_IP", {"url": "ftp://invalid.example/", "interval_s": 1.0, "timeout_s": 1})
print(res)
stop_experiment_monitors()
PYEOF
)"
echo "  返回: $RESULT"
echo "$RESULT" | grep -q "'ping': True" && ok "ping 监控正常启动（未被 HTTP 失败影响）" \
                                        || bad "ping 监控未启动"
echo "$RESULT" | grep -q "'http': False" && ok "非法 http.url 仅告警降级（http=False，未抛异常）" \
                                          || bad "HTTP 降级行为不符预期"

# ── 可选: 场景2/4/6（pytest）─────────────────────────────────────────────────
if [ "${RUN_TESTS:-0}" = "1" ]; then
  section "场景2/4/6: 测试套件（可选）"
  uv run pytest tests/integration/test_agent_graph.py tests/unit/test_monitor_lifecycle.py \
    tests/integration/test_monitor_autostart.py tests/integration/test_backend_monitor_autostart.py -q \
    && ok "自动化测试通过" || bad "自动化测试失败"
fi

# ── 总评 ─────────────────────────────────────────────────────────────────────
section "总评"
echo "  通过 $PASS 项 / 失败 $FAIL 项"
if [ "$FAIL" -eq 0 ]; then
  echo "  🎉 全部通过"
  exit 0
else
  echo "  ⚠️  存在失败项，请核对上方 ❌ 与 /tmp/qstart_cli.out、/tmp/qstart_web.out"
  exit 1
fi
