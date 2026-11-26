# Quickstart：验证拨测监控自动启动

**特性**: `specs/009-auto-start-monitors/` | **日期**: 2026-11-20

端到端验证场景。验证目标：监控自动启动、Agent 只读、退出清理、测试全绿。

## 🚀 一键验证脚本（推荐）

```bash
bash specs/009-auto-start-monitors/quickstart.sh
```

脚本按顺序执行 场景0（环境检查）→ 场景1 → 场景3 → 场景5，每项输出 ✅/❌，最后给总评；有任何失败退出码非 0。

- 环境变量可覆盖：`TARGET_IP`（默认取 experiment.json）、`MAX_ITERS`（默认 2）、`PORT`（默认 8000）
- `RUN_TESTS=1`：追加跑场景 2/4/6 的自动化测试
- `KEEP_CONFIG=1`：不临时切换安全配置，按当前 experiment.json 原样运行（⚠️ 可能实弹，慎用）
- 细节与安全说明见脚本头部注释

> 提示：场景 1 会向目标发送 1 轮 pps=100、5 秒的 Scapy UDP 流量（auto-approve），仅限实验环境。

以下为手动逐场景执行的等价步骤（脚本即这些步骤的自动化）。

## 前置

```bash
uv sync --extra dev
# 目标 IP 需在 allowlist（src/config/allowlist.json）内，如 10.99.80.160
# 可选：在项目根 experiment.json 的 http.url 填一个可达 URL，验证 HTTP 拨测
```

## 场景 1：CLI 干跑，监控自动就绪（P1 验证）

```bash
uv run python src/main.py --target-ip 10.99.80.160 --max-iters 2 --auto-approve
```

**预期**:
- 启动日志出现「ping monitor started」（以及配置了 http.url 时的「HTTP monitor started」）。
- 全程 Agent 未调用任何 start 工具（工具已不存在）。
- 第一轮流量工具结果 `rtt_during` 非空、`covers_attack_window=true`。
- 实验结束（Ctrl-C 或自然结束）后：`pgrep fping` / `pgrep ping` 无残留。

## 场景 2：Agent 工具集只读（P3 验证）

```bash
uv run pytest tests/integration/test_agent_graph.py -q
```

**预期**: 工具数断言为 19；工具名列表不含 start/stop 四个监控工具，含 `read_ping_stats` / `read_http_stats` / `ping_rtt` / `http_probe`。

## 场景 3：Web 控制台入口（P1 双入口验证）

```bash
uv run uvicorn backend.server:app --host 0.0.0.0 --port 8000
# 浏览器打开 http://localhost:8000，点击「开始实验」
```

**预期**: 后端日志出现监控启动记录；页面 HITL/消息流正常；停止实验后无监控子进程残留；重复启动实验不产生重复监控线程。

## 场景 4：目录模式豁免（FR-004 验证）

```bash
uv run python src/main.py --trex-explore --max-iters 2
```

**预期**: 不出现任何监控启动日志，目录生成流程不受影响。

## 场景 5：失败降级（FR-008 验证）

- 把 allowlist 外目标通过预检后人为造成启动失败（如临时移走 fping 或改坏 http.url）。

**预期**: 出现告警日志，实验继续完成，观测字段为空且提示文案为「监控不可用」而非「请调用 start 工具」。

## 场景 6：测试全绿

```bash
uv run pytest tests/unit/ tests/integration/ -q
```

**预期**: 新增 `test_monitor_lifecycle` 用例通过；除 `test_llm_client.py` 的 8 个既有失败（httpx 0.28.1 mock URL 解析，与本特性无关，webui 分支同样存在）外全部通过。
