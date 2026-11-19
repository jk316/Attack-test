---
description: "Pktgen-DPDK 硬件集成实现任务列表"
---

# 任务：Pktgen-DPDK 硬件集成

**输入**: 来自 `specs/005-pktgen-integration/` 的设计文档

**前置**: [plan.md](plan.md)（差距清单 G1–G7）、[spec.md](spec.md)（用户故事 US1–US3）、[research.md](research.md)（决策 D1–D9）、[data-model.md](data-model.md)、[contracts/](contracts/)

**组织方式**: 任务按用户故事分组，使每个故事可独立实现与测试。本特性为回溯式：现状已实现大部分规格，任务 = 基线确认 + 缺口实现 + 回归防测试。

## 任务总览

| 任务 ID | 阶段 | 所属故事 | 可并行 | 说明 |
|---------|------|---------|:---:|------|
| T001 | 1 搭建 | — | 否 | 运行现有测试基线（含 integration 硬件跳过机制） |
| T002 | 1 搭建 | — | 否 | 依赖与环境确认（uv、pyyaml、vendored 导入路径） |
| T003 | 2 地基 | — | 是 | 契约现状核对表（G1–G5 现状证据） |
| T004 | 2 地基 | — | 否 | D9 配置注入基础（experiment.json + main.py 注入 PKTGEN_SRC_IP） |
| T005 | 3 · US1 | US1 | 是 | 失败测试 G1+G3/D9（tests/unit/test_pktgen_safety_gates.py 新建） |
| T006 | 3 · US1 | US1 | 是 | 失败测试 G2（tests/unit/test_pktgen_adapter.py 扩展） |
| T007 | 3 · US1 | US1 | 否 | 实现 G1：duration>60000 拒绝（src/pktgen/adapter.py） |
| T008 | 3 · US1 | US1 | 否 | 实现 G2：arp dst_ip allowlist（adapter） |
| T009 | 3 · US1 | US1 | 否 | 实现 G3+D9：src_ip 拒绝 + 合法源注入（adapter） |
| T010 | 3 · US1 | US1 | 否 | US1 全绿验证 |
| T011 | 4 · US2 | US2 | 是 | 回归测试：等待封顶 60s + RTT 观测字段（test_pktgen_adapter.py） |
| T012 | 4 · US2 | US2 | 是 | G4 验证测试（依赖 008-G4；tests/integration/test_config_pipeline.py） |
| T013 | 4 · US2 | US2 | 否 | US2 全绿验证 |
| T014 | 5 · US3 | US3 | 是 | 失败测试 G5：replaced_mac 明细（test_pktgen_adapter.py） |
| T015 | 5 · US3 | US3 | 是 | 回归测试：五工具契约（tests/unit/test_pktgen_skills_regression.py 新建） |
| T016 | 5 · US3 | US3 | 否 | 实现 G5：replaced_mac 进结果（adapter） |
| T017 | 5 · US3 | US3 | 否 | US3 全绿验证 |
| T018 | 6 打磨 | — | 是 | G6a：adapter 9 工具 docstring 口径对齐 |
| T019 | 6 打磨 | — | 是 | G6b：system_prompt.j2 口径对齐 |
| T020 | 6 打磨 | — | 否 | quickstart.md 场景 1–6 端到端验证 |
| T021 | 6 打磨 | — | 否 | 全量回归 + 契约不变量终核 |

## 格式：`[ID] [P] [故事] 描述`

- **[P]**: 可并行（不同文件、无依赖）
- **[故事]**: 所属用户故事（US1/US2/US3）
- 描述中包含确切文件路径

## 阶段 1：搭建（基线确认）

**目的**: 回溯式特性没有从零搭建——本阶段确认现有实现与测试基线可信，后续任务只补缺口。

- [x] T001 运行基线测试 `uv run pytest tests/unit/ -v && uv run pytest tests/integration/ -v`，记录当前全绿/已知失败清单；确认 `tests/integration/conftest.py` 的 session 级 Pktgen 可用性检测在硬件不可达时自动跳过（跳过不得误判为失败）
- [x] T002 确认依赖与环境：`uv sync --extra dev`；验证 `pyyaml` 可用、项目根在 `sys.path`（vendored `pktgen_agent` 可被 `src/pktgen/adapter.py` 导入）

---

## 阶段 2：地基（阻塞性前置）

**目的**: 任何用户故事开始前必须完成的核对与配置基础。

**⚠️ 关键**: 本阶段完成前不得开始任何用户故事工作。

- [x] T003 [P] 契约现状核对：对照 `specs/005-pktgen-integration/contracts/pktgen-skill-params.md` 与 `contracts/pktgen-adapter-results.md` 逐项核对 `src/pktgen/adapter.py` 现状，输出「已满足/缺口」核对表——G1（duration 上限）、G2（arp dst_ip allowlist）、G3/D9（src_ip）、G5（replaced_mac）各标注现状证据行号，作为 T007–T015 的实现依据（只读核对，不改代码）
- [x] T004 D9 配置注入基础：在 `src/config/experiment.json` 的 `pktgen` 节新增 `src_ip` 字段（默认取授权实验环境真实源地址，替换 vendored 默认 `192.168.1.1/24`）；在 `src/main.py` 的 env 注入段（`_apply_pktgen_env` 附近）新增 `PKTGEN_SRC_IP`（沿用 `PKTGEN_*` 命名族）。**仅注入配置与环境变量**，适配器消费在 T009 实现。注意：`src/main.py` 与 006 的 G1/G2、008 的 G4 同文件，实施前以 git 状态为准避免互相覆盖

**检查点**: 基线可信、契约核对表完成、PKTGEN_SRC_IP 已注入——用户故事可以开始。

---

## 阶段 3：用户故事 1 - 硬件线速泛洪四件套（优先级：P1）🎯 MVP

**目标**: udp/tcp/icmp/arp 四类泛洪经完整门控（allowlist/HITL/rate 0–100/duration≤60000/src_ip 政策）后编译或下发，补齐 G1/G2/G3+D9 缺口。

**独立测试**: 运行 `tests/unit/test_pktgen_safety_gates.py`（新建）与 `tests/unit/test_pktgen_adapter.py`（扩展）：dry-run 下四工具零流量；duration=120000、rate=150、src_ip 自定义、非白名单 dst_ip 全部被拒绝；白名单目标正常编译并返回产物路径。

### 用户故事 1 的测试 ⚠️

> **注意：先写测试，确认失败后再实现（宪法三·测试伴随）**

- [x] T005 [P] [US1] 失败测试 G1+G3/D9：新建 `tests/unit/test_pktgen_safety_gates.py`——断言 `duration=120000` 的 flood 调用被拒绝且零编译零流量（G1）；断言传入 `src_ip` 参数被拒绝（G3）；断言未传 `src_ip` 时编译参数采用 `PKTGEN_SRC_IP` 注入的合法源、覆盖 vendored 默认 `192.168.1.1/24`（D9，用 monkeypatch 设 env）。写完后运行确认失败
- [x] T006 [P] [US1] 失败测试 G2：扩展 `tests/unit/test_pktgen_adapter.py`——断言 `pktgen_arp_flood(dst_ip="192.168.1.99")` 被拒绝（非白名单）、`dst_ip="10.99.80.160"` 通过且触发 RTT 采样、不提供 `dst_ip` 时正常执行且跳过采样。写完后运行确认失败

### 用户故事 1 的实现

- [x] T007 [US1] 实现 G1：在 `src/pktgen/adapter.py` 新增 duration 上限校验（>60000 拒绝、=0 保留永久发包语义），按 `contracts/pktgen-skill-params.md` 的 DURATION_LIMIT 口径返回 `success=false` 参数错误；接入 `_run_traffic_tool` 执行前（依赖 T005）
- [x] T008 [US1] 实现 G2：在 `src/pktgen/adapter.py` 的 `pktgen_arp_flood` 增加「提供 dst_ip 时必须通过 `validate_target`」分支；不并入 `_SKILLS_WITH_DST_IP`，保持「ARP 无 IP 仍可执行、仅跳过 RTT 采样」的可选语义（依赖 T006）
- [x] T009 [US1] 实现 G3+D9：在 `src/pktgen/adapter.py` 对 udp/tcp/icmp flood 拒绝 LLM 传入的 `src_ip`（G3，与 Scapy 工具「src_ip 必须为空」口径一致）；未传入时把 `PKTGEN_SRC_IP`（env 优先，回退 T004 配置默认）填入参数覆盖 vendored 默认（D9）（依赖 T004、T005）
- [x] T010 [US1] US1 全绿验证：运行 `tests/unit/test_pktgen_adapter.py`、`tests/unit/test_pktgen_safety_gates.py`、`tests/integration/test_pktgen_integration.py`，修复回归；确认四件套 dry-run 零流量、live 模拟端点下发链路（FR-003）不受影响

**检查点**: 用户故事 1 应完整可用且可独立测试（对应 quickstart 场景 1/2/4）。

---

## 阶段 4：用户故事 2 - 默认安全模式与 RTT 观测闭环（优先级：P2）

**目标**: 默认 dry-run 零流量、`--pktgen-live` 实发、同步等待封顶 60s、RTT 观测（attack_window/observation_window/覆盖标志）闭环与配置驱动的参数默认值。

**独立测试**: `tests/unit/test_pktgen_adapter.py` 新增用例（等待封顶、观测字段）+ `tests/integration/test_config_pipeline.py` G4 验证用例。

### 用户故事 2 的测试 ⚠️

- [x] T011 [P] [US2] 回归测试（现状验证+防回归）：扩展 `tests/unit/test_pktgen_adapter.py`——断言 live 下同步等待时长 = min(duration, 60000)ms（monkeypatch `time.sleep` 记录入参）、`duration=0` 不等待、结果含 `attack_window`/`observation_window`/`covers_attack_window` 且 `mode` 标注正确（dry_run/live）
- [x] T012 [P] [US2] G4 验证测试（008 完成后回补）（**依赖 008 完成**）：扩展 `tests/integration/test_config_pipeline.py`——现有 `test_pktgen_defaults_flow_to_adapter` 只断言 env 已设置，需补「工具调用消费」断言：适配器工具未显式传 rate/duration 时采用 `PKTGEN_RATE`/`PKTGEN_DURATION_MS`。⚠️ 实现归属 008（008-G4），本任务在 008 完成后仅补验证测试；008 未完成前本任务阻塞

### 用户故事 2 的验证

- [x] T013 [US2] US2 全绿验证（008 完成后回补）：运行 `tests/unit/test_pktgen_adapter.py`、`tests/integration/test_config_pipeline.py`、`tests/integration/test_pktgen_client.py`（模拟 TCP 端点），确认等待与 RTT 观测行为无回归（依赖 T011、T012）

**检查点**: 用户故事 2 应完整可用且可独立测试（对应 quickstart 场景 1/4/5）。

---

## 阶段 5：用户故事 3 - 高级流量构造与运维工具（优先级：P3）

**目标**: range_scan、packet_sequence（eth_dst_addr 自动填充 + replaced_mac 明细）、pcap_replay（免 allowlist）、stats_monitor 与 stop_and_reset（免 HITL、dry-run 下仅编译）五个工具的完整行为。

**独立测试**: `tests/unit/test_pktgen_adapter.py`（G5 用例）+ `tests/unit/test_pktgen_skills_regression.py`（新建，纯适配器行为、无硬件依赖）。

### 用户故事 3 的测试 ⚠️

- [x] T014 [P] [US3] 失败测试 G5：扩展 `tests/unit/test_pktgen_adapter.py`——断言 `pktgen_packet_sequence` 中伪造 MAC（`00:00:00:00:00:01`、缺失、空串）触发替换且结果含 `replaced_mac` 明细（`[{index, from, to}]` 结构），真实 MAC（如 `f0:c4:78:4c:a5:55`）零误替换。写完后运行确认失败
- [x] T015 [P] [US3] 回归测试（五工具契约）：新建 `tests/unit/test_pktgen_skills_regression.py`——range_scan 参数传递与 dst_ip allowlist（FR-005）、packet_sequence 非法 JSON 拒绝（FR-013）与 ≤16 条目语义、pcap_replay 免 allowlist 且需 HITL（FR-005/006）、stats_monitor 与 stop_and_reset 免 HITL 且任意模式可调用（FR-007）、dry-run 下 stop/stats 仅编译不连接硬件（决策 005-2）

### 用户故事 3 的实现

- [x] T016 [US3] 实现 G5：在 `src/pktgen/adapter.py` 的 `pktgen_packet_sequence` 收集 MAC 替换明细（条目下标、替换前/后值）并写入结果 `replaced_mac` 字段，与 logger 记录保持一致（依赖 T014）

### 用户故事 3 的验证

- [x] T017 [US3] US3 全绿验证：运行 `tests/unit/test_pktgen_skills_regression.py`、`tests/unit/test_pktgen_adapter.py` 全量，修复回归（依赖 T014、T015、T016）

**检查点**: 用户故事 3 应完整可用且可独立测试（对应 quickstart 场景 3）。

---

## 阶段 6：打磨与横切关注点

**目的**: 影响多个用户故事的文档口径与最终验收。

- [x] T018 [P] G6a 文档口径：更新 `src/pktgen/adapter.py` 中 9 个工具的 docstring，与实现一致——duration>60000 拒绝、arp dst_ip 必须过 allowlist、src_ip 禁止自定义（合法源来自配置）、dry-run 下 stop/stats 仅编译
- [x] T019 [P] G6b 提示词口径：更新 `src/prompts/system_prompt.j2` Pktgen 段（约 138 行起工具表与约束说明）对齐同一口径：duration 上限、arp dst_ip allowlist、src_ip 政策、dry-run 止损语义
- [x] T020 端到端验证：按 `specs/005-pktgen-integration/quickstart.md` 场景 1–6 逐条执行并核对预期结果（含 `--pktgen-rate/--pktgen-duration` 生效、MAC 替换明细、live 模拟端点门控）
- [x] T021 全量回归 + 契约终核：`uv run pytest tests/ -v` 全绿；逐条核对 `contracts/pktgen-skill-params.md` 第 3 节与 `contracts/pktgen-adapter-results.md` 第 5 节不变量

---

## 依赖与执行顺序

### 阶段依赖

- **搭建（阶段 1）**: T002 → T001（依赖装好才跑基线）
- **地基（阶段 2）**: 依赖阶段 1；T003/T004 可并行；阻塞所有用户故事
- **用户故事（阶段 3–5）**: 依赖地基；按优先级顺序 P1 → P2 → P3 推进
- **打磨（阶段 6）**: 依赖全部目标故事完成

### 每个用户故事内部

- 测试（T005/T006/T011/T012/T014/T016）先写并确认失败，再实现
- US1：T007 ← T005；T008 ← T006；T009 ← T004 + T005；T010 ← T007/T008/T009
- US2：T013 ← T011/T012；T012 ← 008-G4（跨特性依赖）
- US3：T016 ← T014；T017 ← T014/T015/T016
- 故事完成后再进入下一优先级

### 跨特性依赖（重要）

- **T012 依赖 008-G4**：`PKTGEN_RATE/PKTGEN_DURATION_MS` 的适配器消费实现归 008，本特性只补验证测试；008 完成前 T012 阻塞。
- **T004 的 `src/main.py` 改动**与 006（G1 达标计数/G2 --clean-scripts）及 008 的 main.py 改动同文件——实施时以 git 最新状态为准，避免互相覆盖。

### 并行机会

- 地基阶段：T003 与 T004 可并行（不同文件）
- US1 内：T005（新文件 test_pktgen_safety_gates.py）与 T006（test_pktgen_adapter.py）可并行
- US2 内：T011（unit）与 T012（integration，且依赖 008）可并行
- US3 内：T014（adapter 单测）与 T015（新文件 skills_regression）可并行
- 打磨：T018（adapter docstring）与 T019（提示词）可并行
- 注意：同文件任务（adapter.py 的 T007/T008/T009；test_pktgen_adapter.py 的 T006/T011/T014）必须顺序执行

## 实施策略

### MVP 优先（仅用户故事 1）

1. 完成阶段 1：搭建（T001–T002）
2. 完成阶段 2：地基（T003–T004，关键——阻塞所有故事）
3. 完成阶段 3：用户故事 1（T005–T010）
4. **停下来验证**: 运行 T010 测试并核对 quickstart 场景 1/2/4
5. 可部署/演示（四类泛洪 + 完整安全门控 = 本特性核心价值）

### 增量交付

1. 搭建 + 地基完成 → 基线可信、配置注入就绪
2. 加用户故事 1 → 独立测试 → 部署/演示（MVP！）
3. 加用户故事 2 → 独立测试（含 008-G4 联动）→ 部署/演示
4. 加用户故事 3 → 独立测试 → 部署/演示
5. 打磨横切（文档口径 + 端到端 + 契约终核）

## 备注

- [P] 任务 = 不同文件、无依赖；同文件任务必须顺序执行
- [USn] 标签把任务映射到用户故事（US1 泛洪四件套 / US2 默认 dry-run+RTT 观测 / US3 高级构造与运维）
- 每个用户故事应可独立完成、独立测试
- 实现前确认测试失败（红-绿-重构）
- 每个任务或逻辑分组后提交
- 不修改 vendored `pktgen_agent/`、`dsl/skills/*.yaml`、`topology.yaml`（宪法附加约束，研究 D8）
- data-model 受约束字段映射：duration 规则→T007、src_ip 规则→T009、arp dst_ip→T008、replaced_mac→T016、等待封顶→T011、env 默认→T012、rate/sequences/免门控→T015
