# 实施计划：Pktgen-DPDK 硬件集成

**特性目录**: `specs/005-pktgen-integration/` | **日期**: 2026-11-19 | **规格**: [spec.md](spec.md)

**输入**: 来自 `specs/005-pktgen-integration/spec.md` 的功能规格

## 摘要

把 9 个 Pktgen-DPDK 技能（四类泛洪、范围扫描、报文序列、PCAP 回放、统计监控、停止复位）以受门控的方式接入闭环实验 Agent：经 vendored 编译器把技能 YAML 编译为硬件执行脚本、默认 dry-run 只编译零流量、`--pktgen-live` 经 TCP :22022 实发、攻击期间同步等待（封顶 60s）并采集 RTT 观测、`packet_sequence` 自动填充真实 `dst_mac`，并强制 rate≤100%、攻击时长≤60000ms 与 allowlist/HITL 门控矩阵。

本计划为**回溯式计划**：现有代码（`src/pktgen/adapter.py` + vendored `pktgen_agent/`）已实现大部分规格，实施阶段以「现状 → 规格差距」清单为工作内容，仅补齐缺口，不重写既有链路。

调研结论（详见 [research.md](research.md)）：三个澄清项按推荐默认采纳——duration>60000ms 拒绝（不钳制）、dry-run 下 stop_and_reset 维持现状、arp_flood 的 dst_ip 必须过 allowlist；另新增两个实现决策——禁止 LLM 传入 src_ip（伪造源，宪法四）、工具默认参数改为调用时读 env（宪法六）。

## 技术上下文

**语言/版本**: Python 3.11+（`uv` 管理依赖）

**主要依赖**: LangChain / LangGraph（`@tool` 装饰、`interrupt()` HITL 审批）；pyyaml；vendored `pktgen_agent`（`SkillCompiler` 编译、`PktgenClient` TCP 客户端、`execute_skill_dry_run/live` 执行函数）

**存储**: 文件——`lua_scripts/` 保存时间戳命名的编译产物（审计），`topology.yaml`（主机/端口/端口映射/`dst_mac`）、`dsl/skills/*.yaml`（技能语义唯一来源）

**测试**: pytest（`tests/unit/test_pktgen_adapter.py`、`tests/integration/test_pktgen_client.py`、`tests/integration/test_pktgen_integration.py` 已存在；集成测试带 session 级硬件可达性自动跳过）

**目标平台**: Linux / macOS / Windows 控制台与 Web 控制台（跨平台，不引入 OS 特定逻辑）

**项目类型**: CLI 闭环实验 Agent（LangGraph ReAct）+ Web 控制台，两模式共用同一工具实现

**性能目标**: dry-run 单次工具调用（不含攻击等待）≤2 秒（SC-008）；实发观测窗口覆盖攻击窗口 ≥95%（SC-005）

**约束**: rate 0–100%（编译期）、攻击时长≤60000ms 且同步等待封顶 60s、allowlist/HITL 门控矩阵、禁广播/组播、禁 src_ip 伪造、vendored 代码与上游同步（不修改 `pktgen_agent/`、`dsl/`）

**规模/范围**: 9 个工具、1 个适配器模块（约 685 行）、2 个 vendored 执行函数、1 个拓扑配置；缺口改动集中在适配器 + 文档 + 测试

## 宪法检查

*门禁：阶段 0 研究前必须通过；阶段 1 设计后复查。*

| 宪法条目 | 结论 | 说明 |
|---------|------|------|
| 一、先想清楚再动手 | ✅ 满足 | 本计划即该功能的计划产物；spec.md 已先于实现存在 |
| 二、闭环驱动 | ✅ 满足 | 规格 FR-010/011 覆盖「攻击 → RTT 观测 → 决策」闭环；现状已实现，计划补测试防回归 |
| 三、测试伴随 | ✅ 满足（含缺口） | 已有 `test_pktgen_adapter.py`；新增校验行为（G1/G2/G3/G4/G5）必须同步补单元/集成测试后方可宣称完成 |
| 四、安全优先 | ⚠️ 存在缺口，计划内修复 | allowlist/HITL/上限现状基本满足；缺口：duration>60000ms 未拒绝（G1）、arp_flood dst_ip 未过 allowlist（G2）、src_ip 伪造参数未禁止（G3） |
| 五、可观测驱动 | ✅ 满足 | `build_rtt_observation()` 已附 `rtt_during`/`attack_window`/`observation_window`/覆盖标志；dry-run 模式标注已实现 |
| 六、配置单一来源 | ⚠️ 存在缺口，计划内修复 | env `PKTGEN_RATE/PKTGEN_DURATION_MS` 当前仅用于提示词渲染，工具默认值硬编码在签名（G4） |
| 附加约束·参数上限 | ⚠️ 部分缺口 | rate≤100% 已由 YAML 编译期约束；duration≤60000ms 等待封顶已实现但请求未拒绝（G1） |
| 附加约束·Vendored 同步 | ✅ 满足 | 所有新增校验一律放在适配器层，不改 `pktgen_agent/` 与 `dsl/`（research D8） |
| 附加约束·文档真实性 | ⚠️ 存在缺口 | arp_flood 说明文字与代码口径不一致（说「必须过 allowlist」实则不校验），随 G2 一并修正（G6） |

结论：**门禁通过**——三个安全缺口均有明确修复项且不改变架构；阶段 1 设计完成后复查。

## 项目结构

### 文档（本功能）

```text
specs/005-pktgen-integration/
├── plan.md                          # 本文件（speckit-plan 产出）
├── research.md                      # 阶段 0 产出（决策 D1–D8）
├── data-model.md                    # 阶段 1 产出（6 个关键实体）
├── quickstart.md                    # 阶段 1 产出（端到端验证场景）
├── contracts/
│   ├── pktgen-skill-params.md       # 9 技能参数契约 + 适配器门控规则
│   └── pktgen-adapter-results.md    # 工具结果结构契约
└── tasks.md                         # 阶段 2 产出（speckit-tasks，非本步）
```

### 源代码（仓库根，现状与改动位置）

```text
src/pktgen/adapter.py              # 缺口 G1–G5 的改动位置（唯一源码改动点）
pktgen_agent/compiler/compile.py   # vendored，不改动（参数校验现状来源）
pktgen_agent/client.py             # vendored，不改动（TCP :22022 客户端）
pktgen_agent/tools/execute.py      # vendored，不改动（dry-run/live 执行、产物保存）
dsl/skills/*.yaml                  # 9 个技能定义，不改动（语义唯一来源）
topology.yaml                      # 不改动（host/port/端口映射/dst_mac）
tests/unit/test_pktgen_adapter.py  # 扩展：新增校验行为的单元测试
tests/integration/test_pktgen_client.py       # 扩展：live 门控链集成测试
tests/integration/test_pktgen_integration.py  # 扩展：真实编译器 + 模拟端点
```

**结构决策**: 缺口全部收敛到适配器层——vendored 代码保持与上游同步（宪法附加约束），新增安全校验不进入编译语义，而是作为 Agent 工具的前置门控。测试沿用既有 `unit` / `integration` 分层。

## 实施阶段

- **阶段 0 · 研究**：产出 `research.md`。研究项：R1 duration>60000ms 拒绝方案（→决策 D1）；R2 dry-run 下 stop 语义（→D2 维持现状）；R3 arp dst_ip allowlist 口径（→D3）；R4 src_ip 伪造禁止口径（→D4）；R5 工具默认值 env 注入（→D5）；R6 替换明细进结果（→D6）；R7 产物审计与错误分类现状确认（→D7）；R8 vendored 边界（→D8）。**已完成**。
- **阶段 1 · 设计**：产出 `data-model.md`、`quickstart.md`、`contracts/`（2 份契约）；完成后复查宪法检查（上表 ⚠️ 项转为计划内修复，无新增违反）。**已完成**。
- **阶段 2 · 实现差距**（回溯式：现状 → 规格差距清单，由 speckit-tasks 拆任务）：

| 编号 | 对应 FR/宪法 | 现状 | 差距动作 | 验收口径 |
|------|-------------|------|---------|---------|
| G1 | FR-009 / 附加约束 | 等待封顶 60s 已实现；duration>60000ms 请求未拒绝 | 适配器在执行前拒绝 duration>60000ms 的请求（保留 duration=0 永久发包语义） | 传 120000 返回参数错误、零编译零流量 |
| G2 | FR-005 / 决策 005-3 | arp_flood 的 dst_ip 不校验 | 提供 dst_ip 时调用 `validate_target`（白名单/广播/组播），失败拒绝；不提供仍允许（仅跳过 RTT 采样） | 非白名单 dst_ip 拒绝；白名单通过 |
| G3 | FR-016 / 宪法四 | Pktgen 工具暴露 `src_ip` 参数（默认即伪造源） | 适配器拒绝 LLM 传入 `src_ip`（仅允许省略→使用 vendored 默认），与 Scapy 工具口径一致；默认伪造源按 D9（Lead 定调）：experiment.json 新增合法 `src_ip` 配置经 env 注入适配器，覆盖 vendored 默认 | 传 src_ip 返回明确错误；配置合法源时编译产物含该源 |
| G4 | FR-017 / 宪法六 | `PKTGEN_RATE/PKTGEN_DURATION_MS` 仅用于提示词，签名默认硬编码 | 工具默认值改为调用时读 env（缺省回退现值 50 / 10000ms） | `--pktgen-rate 80` 下未传 rate 的调用使用 80 |
| G5 | FR-012 | MAC 替换仅写日志，结果未反映 | 结果新增替换明细（条目下标 + 替换后 MAC） | 结果含 `replaced_mac` 明细 |
| G6 | 文档真实性 | arp/duration/stop 语义与实现不一致 | 修正工具说明与系统提示词：arp dst_ip 必须过 allowlist、duration>60000 拒绝、dry-run 下 stop 仅编译（决策 D2） | 说明文字与行为一致 |
| G7 | 宪法三 | 缺新行为测试 | 为 G1–G5 补单元测试；集成测试覆盖 live 门控链与编译产物保存 | `uv run pytest tests/ -v` 全绿 |

已满足无需改动（核对即可）：FR-001/002/003/004/006/007/008/010/011/013/014/015/018 及 FR-016 的 dst_ip 广播/组播部分（`validate_target` 已含）。

- **阶段 3 · 任务生成**：由 speckit-tasks 依据本计划产出 `tasks.md`（本步不创建）。

## 复杂度追踪

> 仅当宪法检查存在需论证的违反时填写

无需要论证的违反——三处 ⚠️ 均为缺口而非有意违反，已列入实施阶段 G1–G4 修复。表格留空。
