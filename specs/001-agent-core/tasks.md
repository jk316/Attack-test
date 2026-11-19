# 任务：核心闭环 ReAct Agent 与运行模式

**输入**: 来自 `specs/001-agent-core/` 的设计文档

**前置**: [plan.md](./plan.md)（必需，差距 G1–G8）、[spec.md](./spec.md)（用户故事来源，必需）、[research.md](./research.md)（决策 D1–D6）、[data-model.md](./data-model.md)、[contracts/cli-parameters.md](./contracts/cli-parameters.md)、[quickstart.md](./quickstart.md)

**组织方式**: 任务按用户故事分组，使每个故事可独立实现与测试。项目已存在（回溯式计划），阶段 1 为基线确认；实现任务 = 现状 → 规格差距（plan.md「实施工作清单」）。编号按文档顺序升序。

## 任务总览

| 任务 ID | 阶段 | 所属故事 | 可并行 | 说明 |
|---------|------|---------|--------|------|
| T001 | 1 搭建 | — | 否 | 跑通现有测试基线 |
| T002 | 1 搭建 | — | P | 核对 CLI 参数契约与现状 |
| T003 | 1 搭建 | — | P | 确认环境可复现 |
| T004 | 2 地基 | — | 否 | state.py 奖励公式统一（G2 运行时部分） |
| T005 | 2 地基 | — | P | 奖励/停止纯函数单测 |
| T006 | 2 地基 | — | P | 提示公式文案核对（G2 提示部分） |
| T007 | 2 地基 | — | 否 | 提示渲染断言测试 |
| T008 | 3 US1 | US1 | P | 启动预检单测（先写测试，红） |
| T009 | 3 US1 | US1 | P | reasoning_content 多轮回归测试（G4） |
| T010 | 3 US1 | US1 | P | HITL 轮询集成测试（G5） |
| T011 | 3 US1 | US1 | P | VerboseCallback 单测（G8） |
| T012 | 3 US1 | US1 | 否 | main.py 启动预检实现（G3） |
| T013 | 3 US1 | US1 | 否 | main.py HITL 循环复核与最小修复（G5） |
| T014 | 3 US1 | US1 | 否 | CLI 闭环 e2e + 监控清理（G8） |
| T015 | 4 US2 | US2 | P | 硬裁决确定性单测（先写测试，红） |
| T016 | 4 US2 | US2 | P | 配置注入链单测（G7） |
| T017 | 4 US2 | US2 | 否 | main.py 接入硬裁决（G1） |
| T018 | 4 US2 | US2 | 否 | 提示停止条件文案更新（D1 双保险） |
| T019 | 4 US2 | US2 | 否 | 预算生效集成测试 |
| T020 | 5 US3 | US3 | P | 互斥与 catalog 参数单测（G6） |
| T021 | 5 US3 | US3 | 否 | 目录探索 e2e（G6） |
| T022 | 5 US3 | US3 | 否 | main.py 目录模式行为复核（G6） |
| T023 | 6 打磨 | — | P | quickstart 三场景端到端验证 |
| T024 | 6 打磨 | — | P | 文档真实性更新 |
| T025 | 6 打磨 | — | 否 | 全量测试与覆盖率门禁 |

## 格式：`[ID] [P] [故事] 描述`

- **[P]**: 可并行（不同文件、无依赖）
- **[故事]**: 所属用户故事（US1/US2/US3）
- 描述中包含确切文件路径

## 阶段 1：搭建（基线确认——项目已存在）

**目的**: 建立回归基线并确认设计契约与现状的差距（plan.md 差距表 G1–G8 的核对基准）

- [x] T001 在项目根运行 `uv run pytest tests/unit/ -v` 与 `uv run pytest tests/integration/ -v`，记录通过/失败清单作为回归基线；任何既有失败都记录到本任务说明并在后续任务中作为前置事实（不在此修复与 001 无关的失败）——基线以 Lead 干净环境全量结果为准：`bash .dsh/run-tests.sh tests/ -q` → 346 passed / 9 failed（74s）；9 个既有失败 = 过期断言 17 工具×2（实际 19，预计 005/006/008 修复）+ test_pktgen_client.py 直连真实 Pktgen 被 RST×7（预计 005 修 conftest 跳过逻辑），均与 001 无关、不在此修；统一测试入口 .dsh/run-tests.sh（剥代理 + 占位密钥），跑前 uv run python -V 确认 3.13.x
- [x] T002 [P] 对照 `specs/001-agent-core/contracts/cli-parameters.md` 逐项核对 `src/main.py` 的 parse_args 参数表、默认值与优先级链（CLI > profile > experiment.json > 内置默认），产出差异清单记录到本任务说明（不修改代码）——差异：①`--duration` argparse 兜底默认 5 vs 契约 10（experiment.json 存在时有效默认 10，行为正确；help 文案过时）；②`--pktgen-duration` help 文案 "default 5000" 过时（实际 10000）；③启动预检缺失＝G3/T012 计划差距；④`ATK_IAT_JITTER_MS` 未由 main.py 注入 env（契约 §5 列出，无对应 CLI 参数）。其余参数、优先级链（pre-scan profile→defaults→CLI）、互斥报错、catalog 默认 40 均一致
- [x] T003 [P] 确认 `uv sync` 可复现安装、`.env` 按 `.env_example` 配置 `DEEPSEEK_API_KEY`；记录本机 Python 版本（需 ≥3.11）——`uv sync --extra dev` Resolved 65/Audited 62 ✅；Python 3.13.11 ✅；仓库缺 `.env_example` 文件，`.env` 缺失，已建 gitignored 占位 `.env`（DEEPSEEK_API_KEY=占位符，测试一律 mock 模型不调真实 API）

---

## 阶段 2：地基（阻塞性前置）

**目的**: 统一奖励公式与停止判定（data-model「校验规则汇总」的「奖励公式唯一」条目），阻塞 US2 且为 US1 提供一致的提示口径

**⚠️ 关键**: 本阶段完成前不得开始任何用户故事工作

- [x] T004 在 `src/agent/state.py` 把 `compute_reward` 统一为 `reward = avg_rtt_ms + loss_pct × 10`（保留 avg=inf → 0.0 语义），删除旧 `avg − loss×0.1` 口径并更新 docstring（G2 运行时部分；research.md D2）——同时把 `update_best` 由 best_rtt/rtt_history 旧口径改为基于 `state["reward"]` 维护 `best_reward`（改善归零/无改善 +1）、AgentState 字段 `best_rtt`→`best_reward` 并更新 docstring；tests/integration/test_agent_loop.py 旧口径断言同步更新
- [x] T005 [P] 在 `tests/unit/test_state.py` 为 `compute_reward` / `check_stop_condition` / `update_best` 写单元测试：inf → 0、loss 权重 ×10、达标阈值 `>=`、改善归零 / 无改善 +1（引用 data-model 校验规则）——19 用例，红-绿：先随 T004 实现后立即全绿（新文件无先红证据，旧口径断言在 T004 改动下转红→更新后转绿）
- [x] T006 [P] 核对 `src/prompts/system_prompt.j2`「优化策略 & 奖励函数」「停止条件」两节文案与统一公式一致（现状已为 avg+loss×10，任务 = 核对并按需微调措辞；不得改动其他节）——核对结果：`reward = avg_rtt_ms + loss_pct * 10` 已与统一公式一致、停止条件节无旧口径残留，无需改动
- [x] T007 在 `tests/unit/test_prompt_rendering.py` 为 system_prompt.j2 渲染写测试：断言渲染结果包含统一公式文本与传入的 `max_iters`/`no_improve_limit` 值（渲染入口 `src/agent/graph.py::_build_system_prompt`）——7 用例全绿；渲染仅依赖本地 topology.yaml/env，无网络

**检查点**: 奖励口径全链路唯一——用户故事可以开始实现

---

## 阶段 3：用户故事 1 - 实验员通过 CLI 运行闭环实验并逐轮审批流量（优先级：P1）🎯 MVP

**目标**: CLI 实验闭环安全可用：启动预检拦截非法输入；HITL 审批拒绝 0 报文；多轮推理内容不丢失；运行结束清理监控。

**独立测试**: 以 mock 模型驱动 `src/main.py` 主循环（或直接测其函数），验证「启动 → 预检 → 审批弹窗 → 批准/拒绝 → 结果回传 → 总结 → 清理」全链路，无需真实 LLM 与网络。

### 用户故事 1 的测试（先写测试，确认失败后再实现）⚠️

> **注意：先写测试，确认失败后再实现**

- [x] T008 [P] [US1] 在 `tests/unit/test_main_preflight.py` 写启动预检单测（红）：非 allowlist 目标（如 192.168.1.99）、`max_iters=0`、`no_improve_limit=-1`、`--trex-explore`×`--trex-live` 各断言非零退出与中文错误信息；合规参数断言继续（G3、FR-017、data-model 校验规则「max_iters ≥ 1 / target ∈ allowlist」；T012 完成后转绿）——红证据：ImportError `_run_preflight`（收集错误）；T012 后全绿
- [x] T009 [P] [US1] 在 `tests/unit/test_reasoning_patch.py` 为 reasoning_content 补丁写回归测试（G4、FR-009、SC-002）：mock `src/agent/graph.py::_patch_reasoning_content` 的入站/出站转换函数，构造 ≥3 轮 AIMessage 往返，断言 `additional_kwargs["reasoning_content"]` 在入站提取与出站回传中均不丢失——7 用例全绿（补丁经 graph.py 导入副作用生效）
- [x] T010 [P] [US1] 在 `tests/integration/test_hitl_cli.py` 为 HITL 轮询写集成测试（G5、FR-004/005、SC-004）：mock 模型提议流量工具触发 interrupt → 断言 payload 含 message+params → `Command(resume=False)` 时结果含 `HITL rejected` 且 0 报文、`resume=True` 时继续；覆盖 `--auto-approve` 与 EOF 默认拒绝两个分支（轮询逻辑在 `src/main.py`）——10 用例；暴露偏差：fresh checkout 下 `data/` 目录不存在 → FileHandler 抛 FileNotFoundError（T013 修复）
- [x] T011 [P] [US1] 在 `tests/unit/test_verbose_callback.py` 为 `src/main.py::VerboseCallback` 写单测（G8、FR-013）：INFO 层输出结构行、DEBUG 层全量内容、`MSG_PREVIEW_LEN` 截断标注——10 用例全绿
- [x] T012 [US1] 在 `src/main.py` 的 `main()` 中、`build_graph` 调用之前新增启动预检（G3、FR-017）：`target_ip` 必须 ∈ allowlist（复用 `src/tools/ping_rtt_tool.py` 的 `load_allowlist`/`is_allowlisted` 判定，不得引入第二套 allowlist 逻辑）、`max_iters ≥ 1`、`no_improve_limit ≥ 1`；任一不合规打印明确中文错误并以非零退出码退出（依赖 T008 的红-绿闭环）——新增 `_run_preflight()`（stderr 中文错误 + sys.exit(1)），main() 在 parse_args 后立即调用；互斥组合错误信息改为中文（契约 §4：stderr 中文原因）
- [x] T013 [US1] 在 `src/main.py` 复核 HITL 轮询循环与 FR-004/005 的一致性（拒绝轮 0 报文结果回传、EOF 默认拒绝、`--auto-approve` 标记），按 T010 暴露的偏差最小修复，不改变审批语义（G5）——复核结论：拒绝→`Command(resume=False)`（真实工具返回 "HITL rejected by operator"、0 报文）、EOF→默认拒绝、auto-approve→resume True，均符合 FR-004/005；修复 T010 暴露的偏差：创建 `data/` 日志目录（`log_file.parent.mkdir`）防止 fresh checkout FileNotFoundError，审批语义未变

### 用户故事 1 的实现

- [x] T014 [US1] 在 `tests/e2e/test_cli_loop_e2e.py` 写 e2e 测试（G8、FR-002/014、SC-007）：mock 模型与工具序列驱动完整 CLI 循环（启动→预检→审批→发送→观测→总结），断言最终总结输出、`data/agent.log` 有 LLM I/O 记录、结束后无残留 ping 监控进程（依赖 T012、T013）——4 用例全绿（两轮审批批准/拒绝/EOF、agent.log 含 [LLM INPUT]/[LLM OUTPUT]、mock 监控 stop 断言、预检拒绝不建图）；注：T014 勾选状态由 Lead 复核提醒补记（提交 191c4aa 时漏勾）

**检查点**: 用户故事 1 应完整可用且可独立测试（MVP）

---

## 阶段 4：用户故事 2 - 实验员控制运行预算并依赖收敛早停（优先级：P2）

**目标**: 收敛早停由运行时硬裁决强制执行；预算参数经 CLI/profile/配置链注入且命令行覆盖生效。

**独立测试**: 用确定性 mock 序列（恒无改善 / 恒继续）驱动主循环，断言停止时机精确等于预算（SC-003）；用 parse_args 断言优先级链（SC-005）。

### 用户故事 2 的测试（先写测试，确认失败后再实现）⚠️

- [x] T015 [P] [US2] 在 `tests/unit/test_hard_stop.py` 写硬裁决确定性单测（红，G1、D1、SC-003）：恒无改善序列在第 `no_improve_limit` 轮强制停止、恒改善不提前停、恒继续在 `max_iters` 停止、`covers_attack_window=false` 的轮次不计入无改善计数（D5）；断言 `best_reward`（历史最优奖励）与 `consecutive_no_improve`（连续无改善计数）两字段的更新语义（改善归零/无改善 +1）；针对 `src/agent/state.py` 的裁决纯函数编写，T017 接入后转绿——红证据：ImportError `apply_observation`；T017 后 18 用例全绿
- [x] T016 [P] [US2] 在 `tests/unit/test_config_chain.py` 为配置注入链写单测（G7、FR-007/008/015、SC-005/008）：调用 `src/main.py` 的 `_load_config_defaults`/`_apply_profile`/`parse_args`，断言 CLI > profile（深合并 attack/pktgen/trex）> experiment.json > 内置默认的优先级、未知 profile 报错并列出可用项——13 用例全绿（行为已存在，锁定现状；duration 内置兜底 5 vs 契约 10 的差异已在 T002 记录，未在测试钉死）
- [x] T017 [US2] 在 `src/main.py` 的轮询循环中接入硬裁决（G1、D1、FR-006）：每轮结束后从工具实测结果提取 `avg_rtt_ms`/`loss_pct`（优先 `rtt_during`，回退 `read_ping_stats` 字段；观测不可靠轮跳过计数，D5），调用 `src/agent/state.py` 的 `compute_reward`/`update_best`/`check_stop_condition` 维护 `best_reward` 与 `consecutive_no_improve` 两个状态字段，达标即强制终止并输出总结；裁决仅实验模式生效（目录模式豁免，D6）——新增 `state.apply_observation()`（观测归一化+跳过语义）与 `main._extract_observation()`（ToolMessage JSON 解析）；main() 循环内维护 verdict_state/iteration/seen_count/last_approved，批准轮结算+`check_stop_condition` 强制 break 并输出系统总结；agent/__init__ 导出 apply_observation
- [x] T018 [US2] 在 `src/prompts/system_prompt.j2`「停止条件」节更新文案：明确「系统将在连续无改善达到阈值或达到最大轮数时强制停止」，保留引导模型提前总结的表述（D1 双保险，不改变其他内容）——新增硬裁决说明，保留「完成 {{max_iters}} 轮时停止/连续 {{no_improve_limit}} 轮 reward 无提升时停止」原文（T007 断言不受影响）
- [x] T019 [US2] 在 `tests/integration/test_budget_e2e.py` 写集成测试（SC-003/005 端到端）：mock 模型序列下运行 `src/main.py` 主循环，验证 `--no-improve-limit 2 --max-iters 6` 实际生效且停止时机正确（依赖 T017、T018）——5 用例全绿：恒无改善第 3 轮强制停止（共执行 3 轮）、恒改善跑满 max_iters=6、观测不可靠轮跳过（停止推迟至第 4 轮）、目录模式豁免裁决零审批

### 用户故事 2 的实现

（T017/T018 已完成，见「用户故事 2 的测试」节上方同号条目）

### 用户故事 2 的集成验证

（T019 已完成，见「用户故事 2 的测试」节上方同号条目）

**检查点**: 预算与早停可独立验证，不依赖 US3

---

## 阶段 5：用户故事 3 - 研究员以目录探索模式无人值守生成 TRex 攻击目录（优先级：P3）

**目标**: `--trex-explore` 全程零流量、零审批，工具集仅目录生成工具，摘要写入带时间戳文件且互不覆盖。

**独立测试**: mock 模型输出最终摘要，运行目录模式，断言无 HITL 中断、可用工具集合、摘要文件落盘与时间戳命名（SC-006）。

- [x] T020 [P] [US3] 在 `tests/unit/test_cli_mutex.py` 写单测（G6、FR-012、contracts §3）：`--trex-explore`×`--trex-live` 启动即报错退出；catalog 模式默认 `max_iters=40`；`CATALOG_TARGET`/`EXPLORE_DIRECTION` env 注入逻辑（`src/main.py::parse_args`/`_apply_mode_env`）——10 用例全绿（互斥中文错误、报错前无 env 副作用、catalog 默认 40/10、env 注入三态）
- [x] T021 [US3] 在 `tests/e2e/test_trex_explore_e2e.py` 写 e2e 测试（G6、FR-001/011、SC-006）：mock 模型给出最终摘要 → 断言全程无 interrupt（零审批）、可用工具名集合仅含目录生成工具、`output/trex_attack_catalog_<时间戳>.md` 写入且连续两次运行文件互不覆盖（依赖 T020 完成）——4 用例；红证据：`test_two_consecutive_runs_do_not_overwrite` 失败（同秒时间戳碰撞覆盖，实测复现）；真实 build_graph + CapturingModel 绑定工具名断言 == [run_python_file, write_python_file]
- [x] T022 [US3] 在 `src/main.py` 复核目录模式行为与 FR-011/012 一致性（工具集选择在 `src/agent/graph.py::build_graph`；最终消息为空时不写摘要、正常结束），按 T021 暴露的偏差最小修复（G6）——复核结论：互斥（parse_args 中文报错）、工具集限制（graph.py TREX_TOOLS）均符合；修复①时间戳加微秒 `%Y%m%d_%H%M%S_%f`（连续运行互不覆盖）②最终消息为空时不写摘要并打印提示（修复潜在 UnboundLocalError）

**检查点**: 目录探索可独立验证

---

## 阶段 6：打磨与横切关注点

**目的**: 端到端验证、文档真实性、全量回归门禁

- [x] T023 [P] 按 `specs/001-agent-core/quickstart.md` 场景 A（实验+HITL）/ B（auto-approve）/ C（目录探索）逐场景验证运行与预期结果，把每场景的实际输出对照 SC 判据表记录到本任务说明——**R5 补验完成（2026-11-19 08:06–08:09，Lead 复验）**：用户密钥已有效（主仓库 .env，35 字符，LLM_MODEL=deepseek-flash）。真实 LLM 实测：①场景 C（目录探索）`--trex-explore --max-iters 2` → 真实 LLM 生成 17 个语法通过 cat_*.py（目标≥10）、摘要落盘 output/trex_attack_catalog_20261119_080621_689984.md、退出码 0、零流量零审批 ✅；②场景 A（实验+HITL）`--target-ip 10.99.80.160 --max-iters 1` 输入拒绝 → 真实 LLM 规划参数、HITL 全拒 0 报文、目标无 ICMP 响应 → covers_attack_window=false 轮次被硬裁决跳过（D5 在线验证）、正常结束 exit 0、日志落盘 ✅；③场景 B（--auto-approve）会发真实流量，按安全红线维持 mock 等价验证，不实跑。本次验证 = ①真实 CLI 安全路径（零 LLM 零流量）：预检拒绝 `--target-ip 192.168.1.99` → stderr 中文「不在 allowlist…拒绝启动」exit=1；互斥组合 → 「互斥」exit=2；未知 profile → 列出可用项 exit=1（SC-008 判据满足，均 <1s）②mock 驱动 e2e 等价验证：场景 A/B → tests/e2e/test_cli_loop_e2e.py + tests/integration/test_hitl_cli.py（审批弹窗/批准/EOF 默认拒绝/0 报文/日志/清理，SC-004/SC-007）；场景 C → tests/e2e/test_trex_explore_e2e.py（零审批、工具集 2 个、带时间戳摘要互不覆盖、空摘要不写文件，SC-006）；SC 判据对照：SC-002→test_reasoning_patch、SC-003→test_budget_e2e、SC-005→test_config_chain、SC-001→e2e 构建+首请求 <1s
- [x] T024 [P] 更新文档真实性：`CLAUDE.md` 的「Convergence / early-stop」段落改为硬裁决语义、`src/agent/state.py` 相关描述；若发现其他文档与 G1/G2/G3 落地不符一并修正（不涉及任何行为代码）——CLAUDE.md 收敛段改为运行时硬裁决全文（_extract_observation/compute_reward/update_best/apply_observation/check_stop_condition、D5 跳过、目录豁免、预检）+ state.py 表格行更新；README.md「核心闭环」公式 `avg − penalty(loss)` → 统一公式；PLAN.md / task.md 遗留旧公式文本一并修正
- [x] T025 运行全量门禁：`uv run pytest tests/unit/ -v`、`uv run pytest tests/integration/ -v`、`uv run pytest tests/e2e/ -v`、`uv run pytest --cov=src --cov-report=term-missing`，确认全部通过且无既有基线回归（宪法原则三：宣称完成前测试必须实际运行并通过）——实测：`bash .dsh/run-tests.sh tests/unit/ tests/integration/ tests/e2e/ -q` → **447 passed / 9 failed**（74.7s）：9 个失败与 T001 基线完全一致（17 工具过期断言×2 + Pktgen 真实设备连接×7），无新增回归；相对基线 346 passed 净增 101 个通过用例；覆盖率 `--cov=src` → TOTAL 86%，src/agent/state.py 100%、src/agent/graph.py 95%、src/main.py 94%

---

## 依赖与执行顺序

### 阶段依赖

- **搭建（阶段 1）**: 无依赖，可立即开始（T002/T003 可与 T001 并行）
- **地基（阶段 2）**: 依赖 T001 基线；阻塞所有用户故事
- **用户故事（阶段 3/4/5）**: 依赖地基完成；按优先级 P1 → P2 → P3 顺序推进（US2 依赖 US1 的 T012/T013 对 main.py 的稳定接口）
- **打磨（阶段 6）**: 依赖三个故事全部完成

### 每个用户故事内部

- 测试先写并确认失败，再实现（T008→T012、T015→T017、T010→T013）
- 核心实现先于集成（US1：T012/T013 先于 T014；US2：T017/T018 先于 T019）
- 故事完成并独立验证后再进入下一优先级

### 并行机会

- 阶段 1：T001 ∥ T002 ∥ T003（不同关注面）
- 阶段 2：T005 ∥ T006 可与 T004 交错（T005 红-绿依赖 T004 完成）
- US1：T008、T009、T010、T011 四者互相独立，可并行；T012/T013 依赖各自测试先行
- US2：T015 与 T016 可并行；T017/T018 依赖测试先行
- US3：T020 可先行（T021 依赖其完成）
- 打磨：T023 ∥ T024

## 实施策略

### MVP 优先（仅用户故事 1）

1. 完成阶段 1（T001–T003）：基线确认
2. 完成阶段 2（T004–T007）：奖励口径地基
3. 完成阶段 3（T008–T014）：用户故事 1
4. **停下来验证**: 以 T014 e2e + quickstart 场景 A 独立测试 US1
5. 可演示：`uv run python src/main.py --target-ip 10.99.80.160 --max-iters 3` 安全闭环运行

### 增量交付

1. 基线 + 地基 → 奖励口径统一
2. 加 US1 → 独立测试 → MVP 可演示
3. 加 US2 → 独立测试 → 预算硬裁决生效
4. 加 US3 → 独立测试 → 目录探索可无人值守
5. 打磨（T023–T025）→ 全量门禁通过

## 备注

- [P] 任务 = 不同文件、无依赖
- [故事] 标签把任务映射到用户故事以便追溯
- 每个用户故事应可独立完成、独立测试
- 实现前确认测试失败（红-绿）；每个任务或逻辑分组后提交
- 同文件约束：`src/main.py` 的修改集中在 T012/T013/T017/T022（按阶段顺序执行，不并行）；`src/agent/state.py` 修改集中在 T004/T017
- Web 控制台宿主的硬裁决接入由 007-web-console 规格任务处理，不在本特性范围（plan.md 假设）
- 避免：含糊任务、同文件冲突、破坏独立性的跨故事依赖
