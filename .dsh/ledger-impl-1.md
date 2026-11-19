# 恢复账本 — impl-first-half（001-004）

工作目录: /Users/zxkkk/code/Attack-test/.dsh/worktrees/fbcdd24e（分支 worktree/fbcdd24e）
每完成一个任务追加一行: `[x] T00N — 变更文件 — 测试结果`

## 001-agent-core 基线（T001，2026-11-19）——官方版（Lead 干净环境全量）

**以 Lead 报告为准**（commit 7be0181 已修 web-async 依赖）：`bash .dsh/run-tests.sh tests/ -q` → **346 passed / 9 failed**（74s）。

9 个既有失败（不归 001 修复，前置事实）：
1. tests/integration/test_agent_graph.py::test_graph_has_17_tools + tests/integration/test_pktgen_integration.py::test_tool_count_is_17 → 过期断言 17 工具（实际 19）。预计 005/006/008 修复。
2. tests/integration/test_pktgen_client.py ×7 → ConnectionResetError [Errno 54]：直连真实 Pktgen（10.99.80.222:22022），本机无硬件；conftest 可用性检查不足。预计 005 修复跳过逻辑。

**统一测试入口：`bash .dsh/run-tests.sh <pytest args>`**（剥代理变量 + 无密钥注入占位 + uv run pytest）。全量跑或涉及 httpx/openai/graph 构建的测试一律用它。跑前 `uv run python -V` 确认 3.13.x（PATH 有 3.9 陷阱）。

（我方早期自跑 unit 253P/8F、integration 71P/11F，其中 test_web_experiment 2 失败已被 Lead 环境修复消除；test_llm_client.py 8 失败在 Lead 干净环境（剥代理）下**通过**——是代理环境导致，非真实缺陷。以 346P/9F 为准。）

## T002 差异清单（核对 contracts/cli-parameters.md vs src/main.py，仅记录不改码）

1. `--duration`：argparse 兜底默认 5（代码）vs 契约「attack.duration_s（10）」；experiment.json 存在时有效默认 10 ✅。help 文案 "default 5" 过时。
2. `--pktgen-duration`：help 文案 "default 5000" 过时（实际兜底 10000）✅ 行为正确。
3. 无启动预检（max_iters/no_improve_limit ≥1、target∈allowlist）→ 即 G3/T012 计划差距，不在本任务修。
4. `ATK_IAT_JITTER_MS` 未由 main.py 注入 env（契约 §5 列出；无对应 CLI 参数，experiment.json attack.iat_jitter_ms=0 存在）→ 记录，报 Lead。
5. 其余参数（target-ip/pcap-path/log-path/max-iters/no-improve-limit/auto-approve/verbose/pps/packet-size/flow-count/pktgen-*/trex-*/catalog-target/explore-direction/instruction/profile）与优先级链（pre-scan profile → argparse defaults → CLI 覆盖）、互斥（trex-explore×trex-live → parser.error）、catalog 默认 max_iters=40 均与契约一致 ✅。

## T003 环境可复现

- `uv sync --extra dev`：Resolved 65 packages，Audited 62 ✅。
- Python 3.13.11（≥3.11 ✅）。
- `.env_example` 在仓库中**不存在**（CLAUDE.md 提及但缺文件，属文档漂移）。`.env` 缺失；已创建 .env 占位 `DEEPSEEK_API_KEY=sk-placeholder-not-a-real-key`（gitignored，不进提交）。无真实密钥，所有测试 mock 模型，不调用真实 LLM。

## 任务账

[x] T001 — 无变更 — unit 253P/8F(预存在 src/llm)、integration 71P/11F(预存在：17 工具断言×2、Pktgen 连接×7、pytest-asyncio×2)
[x] T002 — 无变更 — 差异清单见上（4 项，均为记录级）
[x] T003 — .env（新建占位，gitignored） — uv sync 可复现；Python 3.13.11
[x] T004 — src/agent/state.py + tests/integration/test_agent_loop.py — compute_reward 统一为 avg+loss×10；update_best 改 best_reward 语义；31 相关测试绿
[x] T005 — tests/unit/test_state.py（新建 19 用例） — 全绿
[x] T006 — 无变更（核对 system_prompt.j2 两节与统一公式一致） — 核对通过
[x] T007 — tests/unit/test_prompt_rendering.py（新建 7 用例） — 全绿
[x] T008 — tests/unit/test_main_preflight.py（新建 12 用例） — 红证据：ImportError _run_preflight；T012 后 12/12 绿
[x] T009 — tests/unit/test_reasoning_patch.py（新建 7 用例） — 全绿
[x] T010 — tests/integration/test_hitl_cli.py（新建 10 用例） — 暴露 data/ 缺失 FileNotFoundError 偏差；T013 修复后全绿
[x] T011 — tests/unit/test_verbose_callback.py（新建 10 用例） — 全绿
[x] T012 — src/main.py（_run_preflight + is_allowlisted 复用 + 互斥错误改中文） — preflight 12/12 绿
[x] T013 — src/main.py（data/ 日志目录 mkdir） — HITL 10/10 绿；审批语义未变
[x] T015 — tests/unit/test_hard_stop.py（新建 18 用例） — 红证据：ImportError apply_observation；T017 后全绿
[x] T016 — tests/unit/test_config_chain.py（新建 13 用例） — 全绿（锁定已存在注入链）
[x] T017 — src/agent/state.py(apply_observation)、src/agent/__init__.py、src/main.py(_extract_observation+循环裁决接入) — 48 项相关测试绿
[x] T018 — src/prompts/system_prompt.j2（停止条件节硬裁决文案） — T007 断言保持绿
[x] T019 — tests/integration/test_budget_e2e.py（新建 5 用例） — 全绿（恒无改善 3 轮停/恒改善 6 轮停/不可靠跳过/目录豁免）
[x] T020 — tests/unit/test_cli_mutex.py（新建 10 用例） — 全绿
[x] T021 — tests/e2e/test_trex_explore_e2e.py（新建 4 用例） — 红证据：同秒时间戳碰撞覆盖；T022 后全绿
[x] T022 — src/main.py（catalog 时间戳加微秒 + 空摘要不写文件并提示） — e2e 4/4 绿
[x] T023 — 无代码变更（验证） — 真实 CLI 安全路径 3 条通过（预检 exit=1/互斥 exit=2/未知 profile exit=1）；真实 LLM 场景因密钥无效不可跑（已报 Lead）；mock e2e 等价验证全绿
[x] T024 — CLAUDE.md/README.md/PLAN.md/task.md（文档真实性） — 无行为代码变更
[x] T025 — 全量门禁 — 447P/9F（9 个与基线完全一致，无新增回归；基线 346P 净增 101）；覆盖率 86%（state.py 100%、graph.py 95%、main.py 94%）

## Lead 001 验收后修正（2026-11-19）
[x] T014 — tests/e2e/test_cli_loop_e2e.py — 补勾选（Lead 复核提醒漏勾；4 用例已随 191c4aa 提交）
[x] R5 — specs/001-agent-core/tasks.md — T023 说明标注「真实 LLM 三场景验证待 .env 密钥有效后补验」
[x] R4 裁定 — ATK_IAT_JITTER_MS env 注入归属 002，在 002 T015/T016 后补（main.py 注入块 + 断言测试），T015 说明注明

## 002-scapy-traffic-tools（25/25）
[x] T001 — 基线记录 — unit+integration 427P/9F（与 001 一致）
[x] T002 — 差异清单（记录） — 见 tasks.md 说明
[x] T003 — 常量核对（记录） — 全一致；mixed 重复常量漂移风险记录
[x] T004 — tests/unit/test_traffic_send_tool.py（+8） — 全绿
[x] T005 — tests/unit/test_ping_rtt_tool.py（+7） — 全绿（15）
[x] T006 — tests/unit/test_log_tool.py（+2） — 全绿（11）
[x] T007 — tests/unit/test_mixed_traffic_tool.py（+7） — 全绿（43）
[x] T008 — tests/unit/test_traffic_send_tool.py（TestClampAnnotations） — 红 6 用例→T011 后全绿
[x] T009 — 同上（TestInterruptionAnnotation） — 红→T012 后全绿
[x] T010 — tests/unit/test_tools_hitl.py（新建 5） — 全绿
[x] T011 — src/tools/traffic_send_tool.py（requested_params/clamped + _clamped_fields） — 全绿
[x] T012 — src/tools/traffic_send_tool.py（completed/interrupt_reason） — 全绿
[x] T013 — tests/integration/test_traffic_send_flows.py（新建 2） — 全绿
[x] T014 — tests/unit/test_mixed_traffic_tool.py（TestMixedJitterParam） — 红 5→T015 后全绿
[x] T015 — src/tools/mixed_traffic_tool.py（iat_jitter_ms 参数化）；**R4**：src/main.py（parse_args.iat_jitter_ms + _inject_attack_env）+ tests/unit/test_config_chain.py（+3） — 全绿
[x] T016 — src/agent/tools.py（mixed 封装同步）+ src/prompts/system_prompt.j2（参数表行） — 全绿
[x] T017 — src/tools/mixed_traffic_tool.py（四标注字段）+ tests/unit/test_mixed_traffic_tool.py（TestMixedAnnotations 4） — 全绿
[x] T018 — tests/integration/test_mixed_traffic_send.py（新建 3） — 全绿
[x] T019 — tests/unit/test_tools_hitl.py（+3 mixed） — 全绿
[x] T020 — tests/unit/test_agent_tools_wrappers.py（新建 4） — 全绿
[x] T021 — tests/integration/test_ping_log_e2e.py（新建 4） — 全绿
[x] T022 — src/tools/ping_rtt_tool.py（拒绝 raise→契约 dict）+ test_ping_rtt_tool.py 5 用例更新 + e2e test_non_allowlist 更新 — 全绿（发现并修复 1 个契约回归）
[x] T023 — src/agent/tools.py（traffic_send docstring 上限修复） — grep 复核无残留
[x] T024 — CLAUDE.md（docstrings 已修复段 + 标注/抖动行为段 + Key Files 行） — 无行为代码
[x] T025 — 全量门禁 — 506P/9F（9 个基线失败无回归；基线 427P 净增 79）；覆盖率 87%；quickstart 场景按安全红线改等价验证（真实流量命令未执行）

## 003-ping-monitor-rtt（20/21 完成，T018 范围冲突报 Lead）
[x] T001 — 基线 72P/0F（三文件）
[x] T002 — 环境：fping /usr/bin/fping ✅；uv sync --extra dev 修复本 worktree 缺 pytest（3.9 回退陷阱）
[x] T003 — src/config/experiment.json（ping_monitor 节）
[x] T004 — src/main.py（args.ping_monitor + _inject_ping_monitor_env）
[x] T005 — tests/unit/test_ping_monitor.py（TestConfigDrivenBuild 10） — 红 5→T006 全绿
[x] T006 — src/tools/ping_monitor.py（env 配置化 + _env_int/_env_float + 频率下限钳制）+ src/agent/tools.py（两个包装 None 缺省透传） — 全绿
[x] T007 — test_ping_monitor.py（TestFpingQSummaryParsing 4） — 全绿
[x] T008 — test_ping_monitor.py（TestCrossLanguageLoss 6）+ ping_monitor.py（补「无法访问目标主机」模式） — 红 1→全绿
[x] T009 — test_ping_monitor.py（TestWeightedStats 3） — 全绿
[x] T010 — test_ping_monitor.py（TestConcurrentQueries 1） — 全绿
[x] T011 — tests/integration/test_ping_monitor_lifecycle.py（新建 3） — 全绿（Popen 包装：真实命令断言 + sleep 模拟，零网络）
[x] T012 — test_rtt_window.py（TestFiveClassCoverage 6） — 红 3（不变式）→T014 全绿
[x] T013 — test_rtt_window.py（TestRttDuringAggregation 3） — 全绿（首版时间点断言有舍入容差问题，已修）
[x] T014 — src/tools/rtt_window.py（短窗口分支 rtt_during→null，契约不变式修复）+ tools.py 只读确认 ✅
[x] T015 — test_ping_rtt_tool.py（TestRejectionDualEntry） — 全绿
[x] T016 — test_ping_rtt_tool.py（TestStatsSectionParsing 4） — 全绿
[x] T017 — tools.py ping_rtt 只读确认 ✅；场景 2 安全等价验证
[ ] T018 — backend/experiment.py 清理 — **范围冲突**：禁改 backend/，只读确认缺口存在，报 Lead（归 007）
[x] T019 — quickstart.md 核对 — 与实现一致，无需修订
[x] T020 — 全量门禁 548P/9F（基线一致，净增 76）+ 场景 1-5 mock 等价证据 + 覆盖率 88%
[x] T021 — FR-001~016 收敛自查 — 仅 FR-016 Web 清理缺口（=T018），报 Lead
[x] R6 — specs/002-scapy-traffic-tools/quickstart.md（场景 A 命令改 -m 形式，已逐一验证可跑） — 随 003 提交

## Lead 003 验收后修正
[x] T003/T004 — specs/003-ping-monitor-rtt/tasks.md — 去重补勾（Lead 复核提醒：编辑时产生重复条目，已删除 64-65 行旧未勾项）
[x] R7 — T018 改派 007 梯队（Lead 裁定），本梯队不再处理

## 004-pcap-profile（23/24 完成，T017 范围冲突报 Lead）
[x] T001 — 基线 14P/0F；G-001 缺陷行只读确认
[x] T002 — 环境确认（无 sample.pcapng → Scapy 夹具）
[x] T003 — src/config/experiment.json（pcap_profile 节）
[x] T004 — src/main.py（_inject_pcap_profile_env）
[x] T005 — src/tools/pcap_profile_tool.py（env 读取）+ src/agent/tools.py（count=None）
[x] T006 — test_pcap_profile_tool.py 夹具四件套
[x] T007 — TestFiveTupleFlowCount 4 用例（红证据=T001 缺陷行确认）
[x] T008 — 流键修复（严格 5 元组）
[x] T009 — TestUdpOnlyIsolation 2
[x] T010 — TestIatStats 3
[x] T011 — TestRankingsHistPayload 3
[x] T012 — TestTruncationNote 2
[x] T013 — 场景 1 端到端（包装层实测七字段+notes）
[x] T014 — tests/unit/test_profile_to_params.py（TestMappingRules/TestClamping 16）
[x] T015 — src/tools/profile_to_params.py（新模块纯函数）
[x] T016 — src/main.py（_explicit_flags + _apply_profile_seeds + user message 映射行）+ TestCliSeedIntegration 5
[ ] T017 — backend/experiment.py Web 映射接入 — **范围冲突**，报 Lead 归 007
[x] T018 — 场景 3 e2e（映射与重算一致 + --pps 500 覆盖）
[x] T019 — TestRobustness 5（红：tcp_only 无 UDP 说明）
[x] T020 — 无 UDP 显式说明实现
[x] T021 — 场景 4 手工验证（File not found/空文件）
[x] T022 — 全量门禁 586P/9F（基线一致，净增 38）；覆盖率 89%
[x] T023 — FR 收敛自查（仅 FR-011 Web 入口缺口 =T017）
[x] T024 — quickstart 核对无需修订
