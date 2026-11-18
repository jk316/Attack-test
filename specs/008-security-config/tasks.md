---
description: "安全约束与配置体系（横切关注点）实现任务列表"
---

# 任务：安全约束与配置体系（横切关注点）

**输入**: 来自 `specs/008-security-config/` 的设计文档（spec.md、plan.md、research.md、data-model.md、contracts/experiment-config.md、contracts/allowlist-config.md、contracts/hitl-payload.md、quickstart.md）

**前置**: spec.md（用户故事来源）、plan.md（差距 G1–G6）

**组织方式**: 任务按用户故事分组，使每个故事可独立实现与测试。本特性为**横切 + 回溯式**：现状已实现大部分门控（validate_target、常量钳制、HITL 矩阵、TRex 沙箱、profiles），任务内容 = plan.md 中 G1–G6 差距的落地；多含「先写测试暴露缺口、再实现」的任务。

## 任务总览

| 任务 ID | 阶段 | 所属故事 | 可并行 | 说明 |
|---------|------|---------|--------|------|
| T001 | 1 搭建 | — | 否 | 运行现有测试基线并记录 |
| T002 | 1 搭建 | — | 否 | validate_target 契约测试（核对现状） |
| T003 | 2 地基 | — | 否 | 上限常量与宪法数值绑定测试 |
| T004 | 2 地基 | — | 是 | HITL payload 统一结构测试（先写，现状失败） |
| T005 | 3 | US1 | 是 | G3 Scapy 两处审批 payload 统一（src/agent/tools.py） |
| T006 | 3 | US1 | 是 | G3 Pktgen _hitl_gate 统一（src/pktgen/adapter.py） |
| T007 | 3 | US1 | 是 | G3 TRex _execute_live 统一（src/trex/tools.py） |
| T008 | 3 | US1 | 否 | G4 duration 下发钳制（src/pktgen/adapter.py）+ 先写测试 |
| T009 | 3 | US1 | 否 | 门控矩阵集合一致性测试 |
| T010 | 3 | US1 | 否 | mixed_traffic src_ip 核验 + 补测试 |
| T011 | 4 | US2 | 是 | G2 配置默认值超限启动警告（src/main.py）+ 先写测试 |
| T012 | 4 | US2 | 是 | G4 Pktgen 工具默认值接 env 注入链（src/pktgen/adapter.py）+ 先写测试 |
| T013 | 4 | US2 | 否 | profiles 优先级与未知预设报错测试 |
| T014 | 5 | US3 | 否 | G1 --auto-approve×实发互斥（src/main.py）+ 先写测试 |
| T015 | 5 | US3 | 否 | 自动批准标记核验 + 断言测试 |
| T016 | 5 | US3 | 否 | dry-run 零流量/explore 零审批回归测试 |
| T017 | 6 打磨 | — | 是 | G5 docstring 上限表述修复（src/agent/tools.py） |
| T018 | 6 打磨 | — | 是 | G5 文档一致性测试（docstring×常量×提示词 0 冲突） |
| T019 | 6 打磨 | — | 是 | 系统提示/README 上限表与门控矩阵核对 |
| T020 | 6 打磨 | — | 否 | G6 全量回归 + quickstart 验收 + SC 收敛矩阵 + 宪法复查 |

## 格式：`[ID] [P] [故事] 描述`

- **[P]**: 可并行（不同文件、无依赖）
- **[故事]**: 所属用户故事（US1/US2/US3）
- 描述中包含确切文件路径

## 阶段 1：搭建（基线确认）

**目的**: 确认现状测试基线与本特性的权威事实基线（上限常量、门控矩阵、validate_target 语义）

- [ ] T001 在项目根运行 `uv run pytest tests/ -v`，记录基线结果；若存在失败，仅做最小修复使基线全绿（不得借机改产品逻辑），并把结果记入本任务的提交说明
- [ ] T002 在 tests/unit/test_target_validation.py 写/核对 validate_target 契约测试（对照 contracts/allowlist-config.md 消费者契约与 data-model「目标校验」检查顺序）：allowlist 空 → "allowlist is empty"；非法格式 → "Invalid IP format"；广播（.255）→ 拒绝；组播（224.0.0.0/4）→ 拒绝；非白名单 → "Target … not in allowlist"；合法白名单 IP → 通过。先跑一次记录现状（预期基本通过，任何失败记入缺口）

**检查点**: 基线全绿、契约语义确认

## 阶段 2：地基（阻塞性前置）

**目的**: 把「上限常量 = 宪法数值」与「统一审批结构」固化为测试契约，作为所有故事的可回归基线

**⚠️ 关键**: 本阶段完成前不得开始任何用户故事工作

- [ ] T003 在 tests/unit/test_limits_constants.py 写上限常量宪法绑定测试：断言 src/tools/traffic_send_tool.py 的 MAX_PPS==20000、MAX_DURATION_S==20、MAX_PACKET_SIZE==1024、MAX_FLOW_COUNT==100、MAX_IAT_JITTER_MS==20，src/tools/mixed_traffic_tool.py 的 MAX_STREAMS==100；注释引用宪法「附加约束」（Pktgen rate≤100%/duration≤60000ms 为跨层约束，由 T008/T009 覆盖）。防未来误改上限的回归测试
- [ ] T004 [P] 在 tests/integration/test_hitl_payload.py 写统一审批结构测试（对照 contracts/hitl-payload.md）：用最小图触发三处 interrupt（traffic_send / pktgen 实发 / TRex 实发，参照 tests/e2e 模式或 mock 图状态快照），断言 payload 均含 `message`（字符串）、`params`（dict）、`scope` ∈ {scapy_traffic, pktgen_traffic, trex_script}；TRex payload 的 params.warning 含「静态扫描非硬边界」声明。先跑一次确认现状失败（scope 缺失、warning 缺声明）

**检查点**: 契约基线就绪——用户故事可以开始并行实现

## 阶段 3：用户故事 1 - 全项目统一的安全门控规则（优先级：P1）🎯 MVP

**目标**: allowlist/广播/组播/src_ip 伪造/上限钳制/HITL 矩阵在 Scapy、Pktgen、TRex 三类入口统一生效且不可绕过；审批内容统一

**独立测试**: quickstart.md 场景 1/2/3/7——同一组违规输入对三类工具全拒且零流量；上限钳制生效值可观测；三处审批提示结构统一（SC-001/002/003/004）

### 用户故事 1 的实现（T004 测试已先行，实现使测试转绿）

- [ ] T005 [P] [US1] 在 src/agent/tools.py 统一 traffic_send 与 mixed_traffic_send 两处 `interrupt()` 审批 payload 为 {message, params, scope:"scapy_traffic"}：mixed_traffic_send 的 params 增加流量规格摘要（流数/协议构成，完整 spec 可截断展示）；保持 message 键不变（007 的 `_extract_hitl` 依赖它，见 contracts/hitl-payload.md「007 联动」）
- [ ] T006 [P] [US1] 在 src/pktgen/adapter.py 统一 `_hitl_gate` 审批 payload 为 {message, params, scope:"pktgen_traffic"}：skill 名与 mode 并入 params（保持 message 键存在），其余技能参数照旧；dry-run 不触发 interrupt 的既有语义不变
- [ ] T007 [P] [US1] 在 src/trex/tools.py 统一 `_execute_live` 审批 payload 为 {message, params, scope:"trex_script"}：params 保留 filename/path/target_ip/detected_ips/code_preview；warning 文本增加「静态 IP 扫描为尽力而为、无法识别域名/拼接/编码构造的目标，请人工审阅」声明（FR-011）
- [ ] T008 [US1] 在 tests/unit/test_pktgen_duration_clamp.py 先写 duration 下发钳制测试：duration=120000（或其他 >60000 值）经 src/pktgen/adapter.py 的 `_run_traffic_tool`/`_execute_skill` 路径后，下发给引擎的 duration ≤60000（现有 `_wait_for_attack` 仅封顶等待 60s，未限制下发参数——先跑确认现状失败）；随后在 src/pktgen/adapter.py 对下发 Pktgen 的 duration 参数显式钳制 ≤60000ms（FR-007、data-model「实验配置」pktgen.duration_ms 约束；宪法附加约束 Pktgen duration≤60000ms）
- [ ] T009 [US1] 在 tests/unit/test_gate_matrix.py 写门控矩阵一致性测试：断言 src/pktgen/adapter.py 的 `_SKILLS_WITH_DST_IP` == {udp_flood, tcp_flood, icmp_flood, range_based_scan, packet_sequence_generation}、`_SKILLS_WITH_HITL` == {udp_flood, tcp_flood, icmp_flood, arp_flood, range_based_scan, packet_sequence_generation, pcap_replay}（arp_flood/pcap_replay 免 allowlist 但保留 HITL；stats_monitoring/safe_stop_and_reset 均不在 HITL 集合——data-model「门控矩阵」）；若集合与契约不符则按契约修正 adapter 集合并更新测试
- [ ] T010 [US1] 核验 src/tools/mixed_traffic_tool.py 对流量规格（JSON spec）内源地址字段的处理：若存在可伪造 src_ip 的路径，按 FR-004 在规格校验处拒绝并返回明确错误；在 tests/unit/test_mixed_src_ip.py 补测试（合法 spec 通过、含源地址伪造的 spec 拒绝）

**检查点**: 用户故事 1 完整可用且可独立测试（quickstart 场景 1/2/3/7 通过）

## 阶段 4：用户故事 2 - 配置单一来源与命名预设（优先级：P2）

**目标**: experiment.json 是默认值唯一来源；env 注入链覆盖 Pktgen 工具；profiles 优先级明确；超限默认值启动告警

**独立测试**: quickstart.md 场景 4/6——改配置无需改代码即生效、profile 覆盖与未知名报错、超限默认值启动警告（SC-005、FR-013/014/015/020）

### 用户故事 2 的实现（测试先行）

- [ ] T011 [P] [US2] 在 tests/unit/test_config_warning.py 先写配置超限告警测试：构造超限 experiment.json（如 attack.pps=99999），断言 main.py 启动校验层输出 WARN 且包含「字段/配置值/钳制后上限值」三要素、进程正常继续；随后在 src/main.py 的配置加载处（load/apply_profile 之后、env 注入之前）实现默认值超限检测层（008-2 决议、contracts/experiment-config.md 语义规则 2、FR-020）
- [ ] T012 [P] [US2] 在 tests/unit/test_pktgen_env_defaults.py 先写 env 注入测试：设置 PKTGEN_RATE/PKTGEN_DURATION_MS 环境变量后调用 src/pktgen/adapter.py 的 @tool 函数（不给显式参数），断言默认值取 env 值（先跑确认现状失败——当前签名硬编码 rate=50.0/duration=5000 且未读 env）；随后在 src/pktgen/adapter.py 为 9 个工具的默认值接入 env 注入链（rate ← PKTGEN_RATE、duration ← PKTGEN_DURATION_MS，缺省回落签名默认），使 experiment.json 的 pktgen.rate=50/duration_ms=10000 生效（FR-013、contracts/experiment-config.md 语义规则 5；本项为 005-G4 的实现归属，005 只做验证）
- [ ] T013 [US2] 在 tests/unit/test_profiles_precedence.py 写 profiles 优先级测试（对照 contracts/experiment-config.md 语义规则 1）：显式 CLI > profile > 基础配置；未知 profile 报错并列出全部可用名（现状已实现，先测后修；与 src/main.py 的 apply_profile 逻辑对齐）

**检查点**: 用户故事 2 完整可用且可独立测试（quickstart 场景 4/6 通过）

## 阶段 5：用户故事 3 - auto-approve 与 dry-run 受控旁路 + 风险提示（优先级：P3）

**目标**: --auto-approve 默认关闭且每次自动批准可见标记；禁止与实发组合；dry-run 零流量；explore 零流量零审批

**独立测试**: quickstart.md 场景 5/8——auto-approve×实发启动报错、无 auto-approve 时审批触发率 100%、自动批准输出标记、dry-run/explore 零流量（SC-004/010、FR-012/017/019）

### 用户故事 3 的实现（测试先行）

- [ ] T014 [US3] 在 tests/unit/test_autoapprove_guard.py 先写互斥测试：`--auto-approve` 与 `--pktgen-live` 或 `--trex-live` 组合时，main.py 启动即报错退出（exit≠0、中文原因）；单独 `--auto-approve`（dry-run）不报错；`--trex-explore`×`--trex-live` 既有互斥保持（先跑确认现状失败——当前无 auto-approve×live 校验）；随后在 src/main.py 参数解析后、env 注入前实现互斥校验（008-1 决议、FR-017、data-model「运行模式」组合约束）
- [ ] T015 [US3] 在 tests/unit/test_autoapprove_marking.py 写自动批准标记测试：auto-approve 路径每次放行必须输出「Auto-approved (--auto-approve)」标记（FR-017；现状 main.py 已打印该标记——核验并固化断言，含拒绝语义不受影响）
- [ ] T016 [US3] 在 tests/integration/test_dryrun_no_traffic.py 写 dry-run/explore 零流量回归测试：默认 dry-run 调用 Pktgen/TRex 工具不触发 interrupt 且不连接硬件（结果 mode=dry_run）；--trex-explore 模式下工具集仅含 write_python_file/run_python_file 且全程无 interrupt（FR-012/FR-019、SC-010）

**检查点**: 用户故事 3 完整可用且可独立测试（quickstart 场景 5/8 通过）

## 阶段 6：打磨与横切关注点

**目的**: 文档一致性与最终收敛

- [ ] T017 [P] 在 src/agent/tools.py 修复 docstring 上限表述（G5）：traffic_send 的 max pps 200→20000、max duration 10s→20s、max packet_size 512→1024、max flow_count 50→100；mixed_traffic_send 同步（pps/duration）；与 src/tools/traffic_send_tool.py 常量一致（FR-016、宪法附加约束「文档真实性」）
- [ ] T018 [P] 在 tests/unit/test_doc_consistency.py 写文档一致性测试（SC-008）：解析 src/agent/tools.py 的 @tool docstring 中上限数字、src/tools/traffic_send_tool.py 常量、src/prompts/system_prompt.j2 上限表三处，断言 0 冲突（自动化守住「文档真实性」）
- [ ] T019 [P] 核对并修订 src/prompts/system_prompt.j2 与 README.md：参数上限表、HITL/allowlist 门控矩阵、--auto-approve 风险提示（新增「禁止与 --pktgen-live/--trex-live 组合」说明）、配置说明与 contracts/experiment-config.md 一致（FR-016、G5）
- [ ] T020 在项目根执行 `uv run pytest tests/ -v` 全量回归；按 quickstart.md 9 个场景验收；对照 spec.md SC-001~SC-010 与 FR-001~FR-020 逐项打勾（收敛矩阵），未满足项追加任务（宪法二）；复查宪法七项原则（重点：四 安全优先零豁免、六 配置单一来源、附加约束上限/文档真实性）

## 依赖与执行顺序

### 阶段依赖

- **搭建（阶段 1）**: 无依赖，可立即开始
- **地基（阶段 2）**: 依赖搭建完成——阻塞所有用户故事（T003/T004 可并行）
- **用户故事（阶段 3–5）**: 依赖地基完成；按优先级 P1→P2→P3 顺序推进（US1 是 MVP；US2/US3 在地基后可与 US1 并行，若人手允许）
- **打磨（阶段 6）**: 依赖所有目标故事完成（T017 需 US1 完成后执行以免与 T005 同文件冲突）

### 每个用户故事内部

- 测试必须先写并确认失败，再实现（T008/T011/T012/T014 均含「先写测试」要求）
- 核心门控实现先于集成验证；故事完成后再进入下一优先级
- T005/T006/T007 为不同文件，实现后可并行；T004 的契约测试是其共同验收

### 并行机会

- 阶段 2：T003、T004 并行（不同文件）
- 阶段 3：T005（tools.py）、T006（adapter.py）、T007（trex/tools.py）三文件互不冲突可并行；T008 与 T012 都改 adapter.py——T008 属 US1、T012 属 US2，**不得并行**（同文件），按阶段顺序执行；T009/T010 为纯测试任务可与实现任务并行
- 阶段 4：T011（main.py）与 T012（adapter.py）不同文件可并行；T013 纯测试可并行
- 阶段 6：T017 与 T019 都涉及 src/agent/tools.py 与 README.md——T018 纯测试任务可与任一并行；T017→T019 建议串行（tools.py 修改后核对外部文档）
- 与 007 联动的并行：008 的 T004 与 007 的 T007/T009 同向（统一审批结构），实现落地后相互重跑兼容性确认（见 007 tasks.md 备注）

## 实施策略

### MVP 优先（仅用户故事 1）

1. 完成阶段 1：基线确认（validate_target 契约测试）
2. 完成阶段 2：地基（上限常量绑定 + 统一审批结构契约测试——关键，阻塞所有故事）
3. 完成阶段 3：用户故事 1（统一安全门控规则）
4. **停下来验证**: 独立测试用户故事 1（quickstart 场景 1/2/3/7 + 全量 pytest 绿）
5. 可部署/演示

### 增量交付

1. 搭建 + 地基完成 → 契约基线就绪
2. 加用户故事 1 → 独立测试 → 部署/演示（MVP！）
3. 加用户故事 2 → 独立测试 → 部署/演示（配置单一来源完整）
4. 加用户故事 3 → 独立测试 → 部署/演示（受控旁路收紧）
5. 打磨 → 全量回归 + 收敛矩阵 + 宪法复查

## 备注

- [P] 任务 = 不同文件、无依赖
- [USn] 标签把任务映射到用户故事以便追溯
- 每个用户故事应可独立完成、独立测试
- 实现前确认测试失败
- 每个任务或逻辑分组后提交
- 避免：含糊任务、同文件冲突、破坏独立性的跨故事依赖
- 本特性为横切：允许任务落在 src/main.py、src/agent/tools.py、src/pktgen/adapter.py、src/trex/tools.py 等既有模块的安全边界处；specs/005 的 G4 验证与本特性 T008/T012 的实现归属已划分（005 只验证，不改 adapter）
- 上限常量为宪法级固定值：任何任务不得把上限改为可配置项（research.md 决策 4）
- 与 007 联动：统一审批结构保持 message 键存在；007 的 `_extract_hitl` 兼容性由 007-T009 负责，本特性只保证契约不破坏该定位规则
