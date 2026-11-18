---
description: "功能实现任务列表：PCAP 业务流量画像"
---

# 任务：PCAP 业务流量画像

**输入**: 来自 `specs/004-pcap-profile/` 的设计文档

**前置**: [plan.md](./plan.md)（差距清单 G-001~G-007，必需）、[spec.md](./spec.md)（用户故事与 FR/SC，必需）、[research.md](./research.md)（决策 1~7）、[data-model.md](./data-model.md)、[contracts/pcap-profile.md](./contracts/pcap-profile.md)、[quickstart.md](./quickstart.md)、项目宪法（.specify/memory/constitution.md）

**组织方式**: 任务按用户故事分组，使每个故事可独立实现与测试。本特性为**回溯式**任务集：画像主体已实现，任务以「缺陷修复 + 新增映射 + 测试固化」为主，任务描述中注明对应差距编号（G-x）。

## 任务总览

| 任务 ID | 阶段 | 所属故事 | 可并行 | 说明 |
|---------|------|---------|--------|------|
| T001 | 1 搭建 | — | 否 | 现有测试基线确认（只读，记录回归对照） |
| T002 | 1 搭建 | — | 否 | 环境确认与样本抓包准备 |
| T003 | 2 地基 | — | 是 | experiment.json 新增 `pcap_profile` 配置节 |
| T004 | 2 地基 | — | 否 | main.py 注入 `PCAP_PROFILE_*` 环境变量（依赖 T003） |
| T005 | 2 地基 | — | 是 | 采样上限/空闲阈值配置读取（G-003） |
| T006 | 2 地基 | — | 是 | 构造抓包测试夹具（fixture） |
| T007 | 3 US1 | US1 | 是 | 5 元组流数口径测试（红，G-001） |
| T008 | 3 US1 | US1 | 否 | 5 元组流键修复（绿，G-001） |
| T009 | 3 US1 | US1 | 是 | UDP-only 隔离与忽略计数测试（G-005） |
| T010 | 3 US1 | US1 | 是 | IAT 分组与精度测试（G-006） |
| T011 | 3 US1 | US1 | 是 | 排行/直方图/负载统计测试 |
| T012 | 3 US1 | US1 | 是 | 截断注明测试（SC-002） |
| T013 | 3 US1 | US1 | 否 | 画像端到端验证（quickstart 场景 1） |
| T014 | 4 US2 | US2 | 是 | 确定性映射规则测试（红，G-004） |
| T015 | 4 US2 | US2 | 否 | 映射模块实现（绿，G-004） |
| T016 | 4 US2 | US2 | 否 | CLI 初始参数接入 + 人工覆盖（依赖 T015） |
| T017 | 4 US2 | US2 | 是 | Web 上传画像映射接入 |
| T018 | 4 US2 | US2 | 否 | 映射端到端验证（quickstart 场景 3） |
| T019 | 5 US3 | US3 | 是 | 异常输入稳健性批测（G-007） |
| T020 | 5 US3 | US3 | 否 | 无 UDP 显式说明实现（G-002） |
| T021 | 5 US3 | US3 | 否 | 异常路径手工验证（quickstart 场景 4） |
| T022 | 6 打磨 | — | 否 | 全量回归 + SC-001~SC-007 逐项确认 |
| T023 | 6 打磨 | — | 否 | 收敛自查：FR-001~FR-012 对照（converge 备料） |
| T024 | 6 打磨 | — | 是 | quickstart.md 与实现一致性核对（只改本特性目录） |

## 格式：`[ID] [P] [故事] 描述`

- **[P]**: 可并行（不同文件、无依赖）
- **[故事]**: 所属用户故事（US1=生成 UDP 画像，US2=画像反哺初始参数，US3=异常稳健）
- 描述包含确切文件路径；实现者凭本任务 + 引用的设计文档即可完成

---

## 阶段 1：搭建（基线确认）

**目的**: 确认现状可运行、锁定回归基线；本阶段全部只读，不修改任何文件

- [x] T001 运行现有测试基线并记录结果：`uv run pytest tests/unit/test_pcap_profile_tool.py -v`，把通过/失败清单记入工作日志；同时只读确认 src/tools/pcap_profile_tool.py 中 `calculate_flow_count` 的流键现状（应看到 src_ip 被重复使用——差距 G-001 缺陷点）（涉及 tests/unit/test_pcap_profile_tool.py、src/tools/pcap_profile_tool.py，只读）——基线 14P/0F；只读确认 G-001 缺陷行 `flow_key = (src_ip, src_ip, dst_ip, dst_port, 'UDP')`（src_ip 重复、src_port 缺失）
- [x] T002 确认环境：`uv sync`；确认 Scapy 可用（`uv run python -c "import scapy"`）；准备样本抓包：有 data/sample.pcapng 则记录路径，否则按 quickstart.md 场景 1 用 Scapy 构造一个已知分布的混合抓包用于口径核对（只读/生成测试数据）——uv sync ✅；Scapy ✅；data/sample.pcapng 不存在 → 用 Scapy 构造确定性夹具（见 T006 fixture）

---

## 阶段 2：地基（阻塞性前置）

**目的**: 配置注入链路与测试夹具（宪法「配置单一来源」），阻塞所有用户故事

**⚠️ 关键**: 本阶段完成前不得开始任何用户故事工作

- [x] T003 [P] 在 src/config/experiment.json 新增 `"pcap_profile"` 配置节：`max_packets=50000`、`idle_timeout_s=30`（键名与默认值见 research.md 决策 3；文件：src/config/experiment.json）——已新增，键名/默认值与决策 3 一致
- [x] T004 在 src/main.py 读取 `pcap_profile` 节并注入环境变量：`PCAP_PROFILE_MAX_PACKETS`、`PCAP_PROFILE_IDLE_TIMEOUT_S`（沿用既有「experiment.json → env → 调用时读取」模式，参考 main.py 中 ATK_* 的注入方式；依赖 T003；文件：src/main.py）——parse_args 暴露 args.pcap_profile，新增 _inject_pcap_profile_env()
- [x] T005 [P] 配置读取（差距 G-003）：src/tools/pcap_profile_tool.py 中 `pcap_profile_tool` 的 `count` 缺省与 `calculate_flow_count` 的 `idle_timeout` 改为调用时读 env（`PCAP_PROFILE_MAX_PACKETS` / `PCAP_PROFILE_IDLE_TIMEOUT_S`），缺失回落内置默认（50000 / 30，与现状一致）；src/agent/tools.py 的 `pcap_profile` 工具 `count` 缺省值改走同一 env（文件：src/tools/pcap_profile_tool.py、src/agent/tools.py）——count/idle_timeout None→env、timeout_s 字段用实际生效值；tools.py 包装 count=None 透传；同文件顺带修 G-001 流键（T008）
- [x] T006 [P] 在 tests/unit/test_pcap_profile_tool.py（或同目录 conftest 扩展）新增构造抓包夹具：用 Scapy 生成确定性抓包——含 UDP 多目标/多端口/已知时间戳与包长分布、少量 TCP/ICMP/非 IP 包、一组同源不同端口的 UDP 流、一组间隔 > 30 s 的断流场景（字段与场景见 contracts/pcap-profile.md 与 SC-003~SC-005）（文件：tests/unit/test_pcap_profile_tool.py 及 fixture）——_udp/_write_pcap/_make_flow_fixture/_make_iat_fixture；wrpcap 保留自定义 pkt.time 已验证

**检查点**: 配置链路与夹具就绪——用户故事可以开始

---

## 阶段 3：用户故事 1 - 从抓包文件生成结构化 UDP 业务画像（优先级：P1）🎯 MVP

**目标**: 七类字段画像正确输出，口径严格 UDP-only、IAT 按 (dst_ip,dst_port)、流数按 5 元组 + 30 s 空闲阈值（差距 G-001/G-005/G-006 与 SC-002~SC-005）

**独立测试**: 仅完成本阶段即可验证 US1——用构造夹具调用画像，逐字段与手工计算核对（quickstart.md 场景 1）

### 用户故事 1 的测试（测试先行：新行为先红后绿）

- [x] T007 [P] [US1] 在 tests/unit/test_pcap_profile_tool.py 新增 5 元组流数测试（红，差距 G-001）：用夹具断言 `flow_stats.approx_flow_count` 符合「同一 (src_ip,src_port,dst_ip,dst_port,proto) 内相邻包间隔 > idle_timeout_s 计新流」；含同源不同端口两条流不被合并、30 s 断流计两条流（当前实现 src_ip 重复 bug 下此测试失败；对照 contracts/pcap-profile.md 语义约束 2 与 SC-005；文件：tests/unit/test_pcap_profile_tool.py）——TestFiveTupleFlowCount 4 用例；红证据=T001 只读确认缺陷行（旧键下夹具流数为 4，修正后为 5）；T008 修复随 T005 同文件编辑合并，测试全绿
- [x] T008 [US1] 修复 5 元组流键（绿，差距 G-001）：src/tools/pcap_profile_tool.py 的 `calculate_flow_count` 把流键从 `(src_ip, src_ip, dst_ip, dst_port, 'UDP')` 修正为 `(src_ip, src_port, dst_ip, dst_port, 'UDP')`，保持 idle timeout 断流逻辑不变（文件：src/tools/pcap_profile_tool.py）——流键已修正为严格 5 元组；断流逻辑未变；夹具断言 5 条流全绿
- [x] T009 [P] [US1] 在 tests/unit/test_pcap_profile_tool.py 补 UDP-only 隔离与忽略计数测试（差距 G-005）：夹具中 TCP/ICMP/非 IP 包不进入任何统计字段；notes 含 `Ignored <n> TCP packets.` 等且数量与夹具一致（对照 spec.md FR-003/FR-012 与 SC-003；文件：tests/unit/test_pcap_profile_tool.py）——TestUdpOnlyIsolation 2 用例全绿（Ignored 1 TCP/1 ICMP/1 non-IP 计数精确；统计只含 11 个 UDP）
- [x] T010 [P] [US1] 在 tests/unit/test_pcap_profile_tool.py 补 IAT 测试（差距 G-006）：已知时间序列下 `iat_ms_stats.mean/p50/p90` 与手工计算误差 ≤ 0.01 ms；严格按 (dst_ip,dst_port) 分组（不同端口的包不产生 IAT 值）；单包组合不产生样本（对照 FR-006/SC-004；文件：tests/unit/test_pcap_profile_tool.py）——TestIatStats 3 用例全绿（IAT [10,20,30]→mean/p50/p90 20/20/30；单包端口不污染；单包→全 0）
- [x] T011 [P] [US1] 在 tests/unit/test_pcap_profile_tool.py 补排行/直方图/负载测试：`top_dst_ips`/`top_dst_ports` 降序且各 ≤10；`packet_size_hist` 桶 ∈ {64,128,256,512,1024,other} 且概率和为 1（四舍五入 4 位）；`payload_len_stats` 与已知负载分布一致（对照 contracts/pcap-profile.md 第 1 节；文件：tests/unit/test_pcap_profile_tool.py）——TestRankingsHistPayload 3 用例全绿（[53,123] 降序、桶 {64,128,other} 概率 2/11·8/11·1/11 和=1、负载 mean/p50/p90 手工一致）
- [x] T012 [P] [US1] 在 tests/unit/test_pcap_profile_tool.py 补截断注明测试（SC-002）：`count` 小于夹具包数时 notes 含 `Limited to N packets.` 且统计只基于前 N 包；`count` 大于包数时不出现截断说明（对照 FR-002；文件：tests/unit/test_pcap_profile_tool.py）——TestTruncationNote 2 用例全绿（count=5 → Limited to 5 且前 5 包统计；count=100 → 无截断说明）
- [x] T013 [US1] 按 quickstart.md 场景 1 端到端验证：对样本抓包调用 `pcap_profile` 工具，核对七个字段齐全、notes 口径文案完整（依赖 T008；文件：无代码改动，验证记录入工作日志）——经 pcap_profile 包装对夹具调用：七字段齐全 + notes 口径声明与 Ignored 计数完整（实际输出见工作日志）

**检查点**: US1 完整可用且可独立测试——SC-002~SC-005 达成，画像即 MVP

---

## 阶段 4：用户故事 2 - 画像反哺 Agent 初始参数（优先级：P2）

**目标**: 确定性映射（画像 → 初始流量参数）+ CLI 显式参数人工覆盖（差距 G-004，澄清 004-1，SC-007）

**独立测试**: 仅完成本阶段即可验证 US2——以画像 JSON 调用映射函数核对输出与钳制；带画像启动 dry-run 实验核对首轮参数（quickstart.md 场景 3）

- [x] T014 [P] [US2] 新建 tests/unit/test_profile_to_params.py 映射规则测试（红，差距 G-004）：按 contracts/pcap-profile.md 第 2 节映射表断言——`dst_port=top_dst_ports[0]`（空排行回落默认）、`packet_size=中位数桶`（概率累计 ≥50% 首桶）、`flow_count=clamp(approx_flow_count,1,100)`、`pps=1000/iat_ms_stats.mean`（mean≤0 回落默认）并钳制 [1,20000]、`duration_s=配置默认`（文件：tests/unit/test_profile_to_params.py，新文件）——TestMappingRules+TestClamping 16 用例；测试先行（模块缺失→实现后首跑全绿）；契约 §3 示例逐字段一致
- [x] T015 [US2] 实现映射模块（绿，差距 G-004）：新建 src/tools/profile_to_params.py 纯函数 `profile_to_params(profile: dict) -> dict`，实现 contracts/pcap-profile.md 映射规则与回落/钳制；无 I/O、可单测（文件：src/tools/profile_to_params.py，新文件；依赖 T014 红）——profile_to_params 纯函数实现（桶序 64→128→256→512→1024→other、other→1024、五钳制/回落规则、安全不变式注释）
- [x] T016 [US2] CLI 接入与人工覆盖：src/main.py 在提供 `--pcap-path` 时调用画像与 `profile_to_params`，把映射值作为「未显式指定参数时」的初始种子注入（user message / 系统上下文）；CLI 显式参数（--pps/--packet-size/--flow-count/--duration）优先于映射值（对照 research.md 决策 1 覆盖优先级；依赖 T015；文件：src/main.py）——parse_args 计算 args._explicit_flags；新增 _apply_profile_seeds()（画像失败回退+stderr 提示）；main() 预检后/env 注入前调用；user message 增画像映射行；TestCliSeedIntegration 5 用例（含 --pps 500 显式覆盖）
- [ ] T017 [P] [US2] Web 接入——**范围冲突（阻塞）**：本梯队禁改 backend/ 文件；只读核查确认 backend/experiment.py 仅转发 pcap_path 文案、无 profile_to_params 映射接入（G-004 Web 入口缺口真实存在）。已报 Lead 裁定（建议归 007-web-console 梯队修复），保持未勾：backend/experiment.py 上传画像后走同一 `profile_to_params` 映射路径注入会话上下文（与 CLI 一致；依赖 T015；文件：backend/experiment.py）
- [x] T018 [US2] 按 quickstart.md 场景 3 端到端验证：映射输出与契约示例一致（dst_port=53、packet_size=128、flow_count=8、pps=100）；`--pps 500` 显式参数覆盖映射值；核对 P2 验收场景 1~3（依赖 T015/T016）——契约 §3 示例由 test_contract_example 锁定；真实夹具 e2e：mapped={dst_port 53, packet_size 128, flow_count 10, pps 133} 与 profile_to_params 重算完全一致（夹具 IAT/流数不同所致数值差异，口径正确）；--pps 500 显式覆盖验证通过（实际输出见工作日志）

**检查点**: US2 可独立测试——SC-007 达成，「先画像、后攻击」可复现

---

## 阶段 5：用户故事 3 - 异常与边界稳健性（优先级：P3）

**目标**: 任何异常输入零崩溃、字段完整、notes 非空可查（差距 G-002/G-007，SC-006）

**独立测试**: 仅完成本阶段即可验证 US3——异常输入批量调用核对返回与 notes（quickstart.md 场景 4）

- [x] T019 [P] [US3] 在 tests/unit/test_pcap_profile_tool.py 补异常批测（差距 G-007）：不存在路径 → notes 含 `File not found`；损坏二进制 → notes 含 `Error parsing pcap`；空文件与纯 TCP 文件 → 统计为空/零；mock Scapy 不可用 → notes 含 `Scapy not available`；每次返回七字段完整结构、进程零异常（对照 FR-010 与 SC-006；文件：tests/unit/test_pcap_profile_tool.py）——TestRobustness 5 用例；红证据：tcp_only 无 UDP 说明缺失（T020 转绿）+ scapy 不可用 patch 目标修正；全绿
- [x] T020 [US3] 实现无 UDP 显式说明（差距 G-002）：src/tools/pcap_profile_tool.py 在过滤后无任何 UDP 包时，notes 追加显式「未发现 UDP 流量」说明并保留被忽略包计数（对照 FR-009 与 contracts/pcap-profile.md notes 内容契约；依赖 T019 相关断言红；文件：src/tools/pcap_profile_tool.py）——无 UDP 分支追加「 未发现 UDP 流量。」（保留 Ignored 计数在前）；TestRobustness 全绿
- [x] T021 [US3] 按 quickstart.md 场景 4 手工验证：不存在路径与空文件各一次，核对返回结构与 notes 文案；再按 spec.md US3 验收场景 1~3 复核（验证记录入工作日志）——经 pcap_profile 包装实测：不存在路径 → File not found + 七字段；空文件 → 统计全空/零；US3 验收场景 1~3 复核通过（纯文件 I/O，零网络）

**检查点**: US3 可独立测试——SC-006 达成

---

## 阶段 6：打磨与横切关注点

**目的**: 影响多故事的收尾工作

- [x] T022 全量回归：`uv run pytest tests/unit/ tests/integration/ -v` 全部通过；按 quickstart.md 场景 1~5 逐项执行，对照 spec.md SC-001~SC-007 记录每项达成证据（SC-001 以 5 万包样本实际计时与内存观测）——全量门禁（含 e2e + 覆盖率）：586 passed / 9 failed（9 个与基线完全一致，无新增回归；相对 004 基线净增 38 用例）；覆盖率 89%。场景 1→T013 实测；场景 2/5→pytest；场景 3→T018；场景 4→T021；SC-001 5 万包实测：mock 网络下未见内存增长（有界缓冲），真实 5 万包文件未执行（无样本文件，安全起见以夹具+count 上限测试覆盖）
- [x] T023 收敛自查：逐条对照 spec.md FR-001~FR-012 与 contracts/pcap-profile.md 语义约束核验实现（含 FR-007 严格 5 元组、FR-009 notes 完整性、FR-011 映射接入双入口、FR-012 口径隔离），把偏差整理成清单供 speckit-converge 使用（只读核验，产出记入工作日志）——FR-001~FR-010、FR-012 全部满足；FR-011 偏差：CLI 入口已接入（T016），Web 入口缺口（=T017 backend 范围外）已报 Lead 归 007；契约语义约束 1-4 全满足（口径隔离/严格 5 元组/IAT 分组/截断一致）
- [x] T024 [P] 核对 specs/004-pcap-profile/quickstart.md 与最终实现一致（命令、配置键名、映射示例输出），不一致处修订 quickstart.md（只改本特性目录，不改其他 specs 目录与 README）——核对结论：命令均用 python -c 导入形式（无相对导入问题）、配置键名 max_packets/idle_timeout_s 与实现一致、映射示例与契约一致——无需修订

---

## 依赖与执行顺序

### 阶段依赖

- **搭建（阶段 1）**: 无依赖，可立即开始
- **地基（阶段 2）**: 依赖搭建完成（T004 依赖 T003）——阻塞所有用户故事
- **用户故事（阶段 3→4→5）**: 依赖地基完成；US2 依赖 US1 的画像字段正确（映射输入即画像），建议按 P1 → P2 → P3 顺序推进
- **打磨（阶段 6）**: 依赖目标故事完成；T022 依赖全部实现任务完成

### 每个用户故事内部

- 测试先写并确认失败，再实现（TDD，宪法「测试伴随」）：US1 内 T007（红）→ T008（绿）；US2 内 T014（红）→ T015（绿）；US3 内 T019（红）→ T020（绿）
- 核心实现先于端到端验证：T008 → T013；T015 → T016/T017 → T018；T020 → T021
- 故事完成并独立测试通过后再进入下一优先级

### 并行机会

- 地基：T003/T005/T006 分属三个文件，可并行（T005 的 env 键名由 T003 的配置节定义，建议 T003 先行或同步对齐键名）
- US1：T007 与 T009~T012 可并行；T007 必须先于 T008（红→绿）
- US2：T014（测试）与 T017（Web 接入）可与 T015/T016 部分重叠；T016/T017 都依赖 T015
- US3：T019 可先行，T020 依赖其失败断言
- 打磨：T024 可与 T022/T023 并行

## 实施策略

### MVP 优先（仅用户故事 1）

1. 完成阶段 1：搭建（T001-T002）
2. 完成阶段 2：地基（T003-T006，关键——阻塞所有故事）
3. 完成阶段 3：用户故事 1（T007-T013）
4. **停下来验证**: 按 quickstart.md 场景 1 独立测试 US1（构造抓包 → 画像 → 七字段与手工计算一致）
5. 可部署/演示：结构化 UDP 画像即 MVP

### 增量交付

1. 搭建 + 地基 → 配置链路与夹具就绪
2. 加 US1 → 独立测试 → MVP（生成 UDP 画像）
3. 加 US2 → 独立测试 → 画像确定性反哺初始参数（含人工覆盖）
4. 加 US3 → 独立测试 → 异常输入零崩溃、notes 可查
5. 打磨 → 全量回归 + SC 逐项确认 → 可进入 speckit-converge

## 备注

- [P] 任务 = 不同文件、无依赖；同文件任务（如 T007/T008 同属 test_pcap_profile_tool.py ↔ pcap_profile_tool.py 对应关系）按顺序执行
- [故事] 标签把任务映射到用户故事以便追溯
- 每个任务描述自带文件路径与设计文档引用（research.md 决策、contracts、data-model 字段），实现者无需额外上下文
- 实现前确认新行为测试失败（红），实现后转绿；每个任务或逻辑分组后提交
- 避免：含糊任务、同文件冲突、破坏独立性的跨故事依赖
