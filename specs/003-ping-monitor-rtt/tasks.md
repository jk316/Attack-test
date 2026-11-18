---
description: "功能实现任务列表：Ping 监控与 RTT 观测"
---

# 任务：Ping 监控与 RTT 观测

**输入**: 来自 `specs/003-ping-monitor-rtt/` 的设计文档

**前置**: [plan.md](./plan.md)（差距清单 G-001~G-007，必需）、[spec.md](./spec.md)（用户故事与 FR/SC，必需）、[research.md](./research.md)（决策 1~7）、[data-model.md](./data-model.md)、[contracts/](./contracts/)、[quickstart.md](./quickstart.md)、项目宪法（.specify/memory/constitution.md）

**组织方式**: 任务按用户故事分组，使每个故事可独立实现与测试。本特性为**回溯式**任务集：现状主体已实现，任务以「差距修复 + 测试固化」为主，任务描述中注明对应差距编号（G-x）。

## 任务总览

| 任务 ID | 阶段 | 所属故事 | 可并行 | 说明 |
|---------|------|---------|--------|------|
| T001 | 1 搭建 | — | 否 | 现有测试基线确认（只读，记录回归对照） |
| T002 | 1 搭建 | — | 否 | 环境确认（uv / fping / allowlist） |
| T003 | 2 地基 | — | 是 | experiment.json 新增 `ping_monitor` 配置节 |
| T004 | 2 地基 | — | 否 | main.py 注入 `PING_MONITOR_*` 环境变量（依赖 T003） |
| T005 | 3 US1 | US1 | 是 | 配置读取与换算测试（红，G-001/G-002） |
| T006 | 3 US1 | US1 | 否 | 配置读取实现（绿，G-001/G-002） |
| T007 | 3 US1 | US1 | 是 | fping -Q 摘要/超时行解析测试（G-005） |
| T008 | 3 US1 | US1 | 是 | 系统 ping 英文/中文跨语言丢包解析测试（G-004） |
| T009 | 3 US1 | US1 | 是 | 加权统计口径测试（G-005，对照契约） |
| T010 | 3 US1 | US1 | 是 | 并发查询一致性测试（SC-004） |
| T011 | 3 US1 | US1 | 否 | 集成测试：命令构造与 20 次启停无孤儿进程（SC-006） |
| T012 | 4 US2 | US2 | 是 | 五类 covers 判定测试（G-005，对照契约） |
| T013 | 4 US2 | US2 | 是 | rtt_during 聚合口径与不变式测试（G-005） |
| T014 | 4 US2 | US2 | 否 | 观测接入确认 + quickstart 场景 3 手工验证 |
| T015 | 5 US3 | US3 | 是 | 拒绝路径双入口测试（G-007，SC-005） |
| T016 | 5 US3 | US3 | 是 | 全丢/超时/跨平台统计段解析测试 |
| T017 | 5 US3 | US3 | 否 | ping_rtt 工具结构化错误确认 + quickstart 场景 2 |
| T018 | 6 打磨 | — | 是 | Web 端 monitor.stop() 清理（G-003，FR-016） |
| T019 | 6 打磨 | — | 是 | quickstart.md 与实现一致性核对（只改本特性目录） |
| T020 | 6 打磨 | — | 否 | 全量回归 + SC-001~SC-007 逐项确认 |
| T021 | 6 打磨 | — | 否 | 收敛自查：FR-001~FR-016 对照（converge 备料） |

## 格式：`[ID] [P] [故事] 描述`

- **[P]**: 可并行（不同文件、无依赖）
- **[故事]**: 所属用户故事（US1=持续监控双后端，US2=攻击期观测对齐，US3=单次测量+allowlist）
- 描述包含确切文件路径；实现者凭本任务 + 引用的设计文档即可完成

---

## 阶段 1：搭建（基线确认）

**目的**: 确认现状可运行、锁定回归基线；本阶段全部只读，不修改任何文件

- [ ] T001 运行现有测试基线并记录结果：`uv run pytest tests/unit/test_ping_monitor.py tests/unit/test_rtt_window.py tests/unit/test_ping_rtt_tool.py -v`，把通过/失败清单记入工作日志，作为后续回归对照（涉及 tests/unit/test_ping_monitor.py、tests/unit/test_rtt_window.py、tests/unit/test_ping_rtt_tool.py，只读）
- [ ] T002 确认环境：`uv sync`；记录 `which fping` 结果（决定高分辨率/回退主路径）；核对 src/config/allowlist.json 的 `hosts` 包含测试目标（如 10.99.80.160）（只读）

---

## 阶段 2：地基（阻塞性前置）

**目的**: 配置注入链路（宪法「配置单一来源」），阻塞 US1 的配置化实现

**⚠️ 关键**: 本阶段完成前不得开始任何用户故事工作

- [ ] T003 [P] 在 src/config/experiment.json 新增 `"ping_monitor"` 配置节：`probes_per_sec=10`、`summary_interval_s=1`、`fallback_interval_s=1.0`、`stats_window_s=5.0`、`max_samples=4000`（键名与默认值见 research.md 决策 2/3；文件：src/config/experiment.json）
- [ ] T004 在 src/main.py 读取 `ping_monitor` 节并注入环境变量：`PING_MONITOR_PROBES_PER_SEC`、`PING_MONITOR_SUMMARY_INTERVAL_S`、`PING_MONITOR_FALLBACK_INTERVAL_S`、`PING_MONITOR_STATS_WINDOW_S`、`PING_MONITOR_MAX_SAMPLES`（沿用既有「experiment.json → env → 调用时读取」模式，参考 main.py 中 ATK_* 的注入方式；依赖 T003；文件：src/main.py）

**检查点**: 配置注入链路就绪——用户故事可以开始

---

## 阶段 3：用户故事 1 - 持续后台监控：高分辨率探测与跨平台回退（优先级：P1）🎯 MVP

**目标**: 高分辨率（10 探针/秒、每秒摘要、加权收发计数）与系统 ping 回退（Windows/Unix、跨语言丢包解析）持续可用，且探测节奏与缓冲上限由配置驱动（差距 G-001/G-002/G-004/G-005 与 SC-001/SC-002/SC-004/SC-006）

**独立测试**: 仅完成本阶段即可验证 US1——启动监控 3 秒后读 1 秒窗口统计（quickstart.md 场景 1）；无 fping 环境自动回退；配置修改后节奏/上限随之生效

### 用户故事 1 的测试（测试先行：新行为先红后绿）

- [ ] T005 [P] [US1] 在 tests/unit/test_ping_monitor.py 新增配置读取与换算测试（红）：mock 环境变量，断言 `_build_fping_q_cmd` 的探测周期 = 1000/probes_per_sec ms、摘要间隔 = summary_interval_s、频率下限 0.1 s 校验（probes_per_sec>10 被拒绝或钳制）、回退间隔取 fallback_interval_s、deque 上限 = max_samples、env 缺失时回落内置默认（对照 research.md 决策 2/3；文件：tests/unit/test_ping_monitor.py）
- [ ] T006 [US1] 实现配置读取（绿，差距 G-001/G-002）：src/tools/ping_monitor.py —— `_build_fping_q_cmd(ip)` 按 env 换算 `-p`（周期 ms）与 `-Q`（摘要间隔 s）；`_build_ping_cmd` 回退间隔读 env；`start()` 的 interval_s 缺省读 fallback_interval_s、`get_stats()` 的 window_s 缺省读 stats_window_s；deque 上限由 max_samples 在实例化时确定（默认 4000，行为与现状一致）；频率下限校验不低于 0.1 s（文件：src/tools/ping_monitor.py）
- [ ] T007 [P] [US1] 在 tests/unit/test_ping_monitor.py 补 fping -Q 解析测试：摘要行 `IP : xmt/rcv/%loss = 10/8/20%, min/avg/max = 2.1/5.7/12.3` → sent=10/received=8/rtt=avg；全丢摘要（0/0/0）→ rtt_ms=null 而非 0；超时行与非摘要行（ICMP 头、空行）→ 不产生样本（对照 contracts/monitor-sample.md；文件：tests/unit/test_ping_monitor.py）
- [ ] T008 [P] [US1] 在 tests/unit/test_ping_monitor.py 补跨语言丢包解析测试（差距 G-004）：英文 "Request timed out"、"Destination host unreachable" 与中文「请求超时」均生成 sent=1/received=0/rtt=null 样本；Unix/Windows 应答行 RTT 提取正确；若测试暴露缺口，在 src/tools/ping_monitor.py 补对应中文不可达模式（如「无法访问目标主机」）（文件：tests/unit/test_ping_monitor.py；必要时 src/tools/ping_monitor.py）
- [ ] T009 [P] [US1] 在 tests/unit/test_ping_monitor.py 补加权统计口径测试（差距 G-005）：get_stats 的 loss_pct = 1 − received/sent、avg_rtt 按 received 加权（fping_q 周期样本与逐探测样本混用时结果与手工计算一致）、未运行时返回 monitor_active=false 且计数 0（对照 contracts/monitor-sample.md 语义约束；文件：tests/unit/test_ping_monitor.py）
- [ ] T010 [P] [US1] 在 tests/unit/test_ping_monitor.py 补并发一致性测试（SC-004）：10 线程并发 get_stats/get_samples_since 共 1000 次，无异常，样本数与串行结果一致（文件：tests/unit/test_ping_monitor.py）
- [ ] T011 [US1] 新增集成测试（SC-006）：在 tests/integration/ 新建真实二进制用例——真实 fping/ping 命令构造正确、连续 20 次 start/stop 后系统无残留探测进程（依赖 T006；文件：tests/integration/ 新文件，如 tests/integration/test_ping_monitor_lifecycle.py）

**检查点**: US1 完整可用且可独立测试——quickstart.md 场景 1 通过，SC-001/SC-002/SC-004/SC-006 达成

---

## 阶段 4：用户故事 2 - 攻击期间的 RTT 观测对齐（优先级：P2）

**目标**: 每次攻击动作附 attack_window / observation_window / rtt_during，covers_attack_window 判定诚实（差距 G-005，SC-003）

**独立测试**: 仅完成本阶段即可验证 US2——用五类样本时序组合调用观测构造核对判定与说明（quickstart.md 场景 3）

- [ ] T012 [P] [US2] 在 tests/unit/test_rtt_window.py 补五类 covers 判定测试（差距 G-005）：未运行（rtt_during=null、note 提示先启动）、无样本、全丢失（loss=100%、rtt_during=null）、窗口过短（duration<1s → false + 原因）、正常覆盖（true + 概况 note，loss≥50% 时追加攻击信号提示）；逐项对照 contracts/rtt-observation.md 判定规则表与示例（文件：tests/unit/test_rtt_window.py）
- [ ] T013 [P] [US2] 在 tests/unit/test_rtt_window.py 补 rtt_during 聚合口径测试：加权 avg/min/max、loss_pct、total_sent/total_received 与手工计算一致；不变式「rtt_during != null ⇒ covers_attack_window == true」；attack_window 的 start/end/duration_s/mode 与 observation_window 的 first/last_sample 时间点正确（对照 contracts/rtt-observation.md；文件：tests/unit/test_rtt_window.py）
- [ ] T014 [US2] 只读确认 src/agent/tools.py 中 traffic_send / mixed_traffic_send 已调用 `build_rtt_observation(get_ping_monitor(), t0, mode="scapy")` 并把结果合并进返回（现状应已满足，FR-011）；按 quickstart.md 场景 3 执行一次攻击工具手工验证三字段齐全（文件：src/agent/tools.py 只读确认；如与契约不符则按 contracts/rtt-observation.md 修正）

**检查点**: US2 可独立测试——SC-003 达成，观测对齐可供 LLM 决策

---

## 阶段 5：用户故事 3 - 单次 ping RTT 测量与安全校验（优先级：P3）

**目标**: 单次测量对 allowlist 目标可用，非法目标 100% 拒绝且零探测（差距 G-007，SC-005/SC-007）

**独立测试**: 仅完成本阶段即可验证 US3——对 allowlist 内/外目标调用测量，核对返回与拒绝行为（quickstart.md 场景 2）

- [ ] T015 [P] [US3] 在 tests/unit/test_ping_rtt_tool.py 补拒绝路径测试（差距 G-007）：对非 allowlist（如 192.168.1.99）、广播（x.x.x.255）、组播（224.0.0.1）、非法格式分别调用 ping_rtt_tool 与 PingMonitor.start，断言抛出明确错误且不构造/启动任何探测进程（对照 spec.md FR-002/FR-014 与 data-model.md 校验规则；文件：tests/unit/test_ping_rtt_tool.py）
- [ ] T016 [P] [US3] 在 tests/unit/test_ping_rtt_tool.py 补全丢与跨平台统计段解析测试：Unix `N packets transmitted, M received, X% packet loss` 与 Windows `Sent = / Received = / Lost =` 两种格式；全丢时 success=true、avg_rtt_ms=inf、loss_pct=100（对照 spec.md US3 验收场景 3；文件：tests/unit/test_ping_rtt_tool.py）
- [ ] T017 [US3] 只读确认 src/agent/tools.py 的 ping_rtt 工具对底层异常返回结构化错误字典（FR-015，现状应已满足）；按 quickstart.md 场景 2 手工验证 allowlist 内测量与拒绝行为（文件：src/agent/tools.py 只读确认）

**检查点**: US3 可独立测试——SC-005/SC-007 达成

---

## 阶段 6：打磨与横切关注点

**目的**: 影响多故事的收尾工作

- [ ] T018 [P] Web 端清理（差距 G-003，FR-016）：在 backend/experiment.py 的实验结束路径（finally 与主动 stop 流程）调用 `get_ping_monitor().stop()`，与 src/main.py finally 保持一致；按 quickstart.md 场景 4 的 Web 分支验证无残留探测进程（文件：backend/experiment.py）
- [ ] T019 [P] 核对 specs/003-ping-monitor-rtt/quickstart.md 与最终实现一致（命令、配置键名、预期输出），不一致处修订 quickstart.md（只改本特性目录，不改其他 specs 目录与 README）
- [ ] T020 全量回归：`uv run pytest tests/unit/ tests/integration/ -v` 全部通过；按 quickstart.md 场景 1~5 逐项执行，对照 spec.md SC-001~SC-007 记录每项达成证据
- [ ] T021 收敛自查：逐条对照 spec.md FR-001~FR-016 与 contracts/ 语义约束核验实现（含 FR-016 双模式清理、FR-013 加权口径、FR-012 覆盖诚实），把任何偏差整理成清单供 speckit-converge 使用（只读核验，产出记入工作日志）

---

## 依赖与执行顺序

### 阶段依赖

- **搭建（阶段 1）**: 无依赖，可立即开始
- **地基（阶段 2）**: 依赖搭建完成（T004 依赖 T003）——阻塞所有用户故事
- **用户故事（阶段 3→4→5）**: 依赖地基完成；建议按优先级 P1 → P2 → P3 顺序推进（US3 与 US1/US2 无文件冲突时也可并行）
- **打磨（阶段 6）**: 依赖目标故事完成；T020 依赖 T018 完成

### 每个用户故事内部

- 测试先写并确认失败，再实现（TDD，宪法「测试伴随」）：US1 内 T005（红）→ T006（绿）；存量行为测试（T007~T010）可在 T006 后并行补齐
- 实现先于集成验证：T006 → T011 → quickstart 场景 1
- 故事完成并独立测试通过后再进入下一优先级

### 并行机会

- 地基：T003 与 T005 可并行（不同文件）
- US1：T007/T008/T009/T010 互不依赖、分属不同测试关注点，可并行（注意 T008 若需改 ping_monitor.py，与 T006 同文件需协调顺序）
- US2：T012 与 T013 可并行
- US3：T015 与 T016 可并行
- 打磨：T018 与 T019 可并行

## 实施策略

### MVP 优先（仅用户故事 1）

1. 完成阶段 1：搭建（T001-T002）
2. 完成阶段 2：地基（T003-T004，关键——阻塞所有故事）
3. 完成阶段 3：用户故事 1（T005-T011）
4. **停下来验证**: 按 quickstart.md 场景 1 独立测试 US1（启动监控 → 读统计 → 后端标注正确）
5. 可部署/演示：持续监控双后端 + 配置化即 MVP

### 增量交付

1. 搭建 + 地基 → 配置注入链路就绪
2. 加 US1 → 独立测试 → MVP（持续监控双后端）
3. 加 US2 → 独立测试 → 攻击期观测对齐可用
4. 加 US3 → 独立测试 → 单次测量 + allowlist 拒绝
5. 打磨 → 全量回归 + SC 逐项确认 → 可进入 speckit-converge

## 备注

- [P] 任务 = 不同文件、无依赖；同文件任务（如 T005/T006 同属 test_ping_monitor.py 与 ping_monitor.py 对应关系）按顺序执行
- [故事] 标签把任务映射到用户故事以便追溯
- 每个任务描述自带文件路径与设计文档引用，实现者无需额外上下文
- 实现前确认新行为测试失败（红），实现后转绿；每个任务或逻辑分组后提交
- 避免：含糊任务、同文件冲突、破坏独立性的跨故事依赖
