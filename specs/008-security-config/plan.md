# 实施计划：安全约束与配置体系（横切关注点）

**特性目录**: `specs/008-security-config/` | **日期**: 2026-11-19 | **规格**: [spec.md](spec.md)

**输入**: 来自 `specs/008-security-config/spec.md` 的功能规格

## 摘要

横切特性：把全项目所有流量入口（Scapy / Pktgen-DPDK / TRex）必须共同遵守的**安全门控统一规则**（allowlist、广播/组播与 src_ip 伪造禁令、参数上限单一来源、HITL 门控矩阵）与**配置单一来源**（experiment.json → 环境变量 → 调用时读取、profiles 命名预设、--auto-approve 受控旁路）规格化，是宪法原则四「安全优先」与原则六「配置单一来源」的落点。

**现状大部分已满足**（validate_target、常量钳制、HITL 矩阵、TRex 沙箱与静态扫描、profiles 已实现），因此本计划采用**回溯式**组织：实施阶段 = 「现状 → 规格差距」的改动清单。主要差距：--auto-approve×实发组合未禁止（G1）、配置默认值超限无启动告警（G2）、HITL 审批内容三处字段不统一（G3）、Pktgen 工具默认值未接入 env 注入链且 duration 未显式钳制（G4）、文档与常量不一致（G5）、测试与收敛矩阵（G6）。规格中 3 项 [需要澄清] 已按 Lead 决议采纳：禁止 auto-approve×实发组合、超限默认值启动警告+钳制、HITL 审批内容统一——决议见 [research.md](research.md)。横切引用 specs/001–007，不重复其工具级细节。

## 技术上下文

**语言/版本**: Python 3.11+

**主要依赖**: LangChain `@tool` / langgraph `interrupt()`（HITL 门禁载体）；PyYAML（topology.yaml 与 vendored 编译器）；现有工具链（Scapy、Pktgen vendored 引擎、TRex subprocess 客户端）

**存储**: 配置文件 `src/config/experiment.json`（默认参数单一来源）、`src/config/allowlist.json`（白名单唯一管理）、`topology.yaml`（主机/端口/dst_mac）；实验日志 JSONL。无数据库

**测试**: pytest（`tests/unit/`、`tests/integration/`，marker：unit/integration/slow）；测试 IP 约定 10.99.80.160（放行）/192.168.1.99（拒绝）

**目标平台**: Linux/macOS/Windows 跨平台（沿用 `sys.platform` 约定）

**项目类型**: 库 + CLI 的横切关注点（跨 specs/001–007 生效，无独立部署单元）

**性能目标**: SC-007 安全校验额外延迟 <50ms（格式/白名单/上限校验不构成可感知阻塞）

**约束**: 参数上限为宪法级固定常量，不纳入可调配置（只能约束生效值，不能放宽）；allowlist/experiment.json 进程内加载一次，运行期修改需重启；文档真实性（docstring/系统提示/README 与常量 0 冲突）

**规模/范围**: 19 个工具 × 3 类入口（Scapy 8 / Pktgen 9 / TRex 2）× 4 种模式组合（dry-run / live / auto-approve / explore）

## 宪法检查

*门禁：阶段 0 研究前必须通过；阶段 1 设计后复查。*

| 宪法原则 | 评估 | 结论 |
|---------|------|------|
| 一、先想清楚再动手（计划先行） | 本 plan.md 与设计制品先行；横切规则同样遵守 | 满足 |
| 二、闭环驱动（全流程收敛） | G6 收敛工作包：以 SC-001~010 为验证矩阵对照代码实测，剩余偏差追加任务直至收敛 | 满足 |
| 三、测试伴随（新功能必配测试） | 每项差距配测试：组合互斥（G1）、启动告警（G2）、统一契约（G3）、钳制与 env 注入（G4）、文档一致性测试（G5） | 满足 |
| 四、安全优先（不可协商） | 本特性即该原则的规格化落点：FR-001~FR-012、FR-018~FR-020 与宪法完全一致——allowlist 强制、广播/组播/src_ip 伪造禁止、上限不可调高、HITL 无豁免捷径；G1 堵住「自动批准+实发」的全自动真实流量路径 | 满足 |
| 五、可观测驱动（数据说话） | 不改动 RTT 观测采集（属 003）；统一 HITL 展示（G3）增强操作员决策信息，与原则同向 | 满足 |
| 六、配置单一来源 | 本特性核心主题：experiment.json→env→调用时读取（FR-013/014）、profiles 一键切换（FR-015）、allowlist 唯一管理（FR-002）；上限常量为宪法级固定值而非可调配置，与原则不冲突（论证见 research.md 决策 4） | 满足 |
| 附加约束：跨平台 / 参数上限 / Vendored 同步 / 文档真实性 | 上限数值逐项一致（FR-005/007）；文档真实性由 FR-016 + G5 落实；Vendored 同步不涉语义分叉 | 满足 |

**结论**: 全部原则满足，无需要论证的违反项。阶段 1 设计后复查：data-model/contracts 与宪法一致性确认（见 data-model.md 末节）。

## 项目结构

### 文档（本功能）

```text
specs/008-security-config/
├── spec.md                 # 功能规格（speckit-specify 产出，横切）
├── plan.md                 # 本文件（speckit-plan 产出）
├── research.md             # 阶段 0 产出（澄清决议 + 技术决策）
├── data-model.md           # 阶段 1 产出（实体/校验/模式互斥状态机）
├── quickstart.md           # 阶段 1 产出（安全验证场景矩阵）
├── contracts/              # 阶段 1 产出
│   ├── experiment-config.md # experiment.json 配置契约
│   ├── allowlist-config.md  # allowlist.json 配置契约
│   └── hitl-payload.md      # 统一 HITL 审批内容契约（008-3 决议）
└── tasks.md                # 阶段 2 产出（speckit-tasks 产出，非本步）
```

### 源代码（仓库根，本计划触碰点）

```text
src/
├── main.py                    # G1：auto-approve×实发互斥；G2：默认值超限启动告警
├── agent/tools.py             # G3：traffic_send/mixed_traffic_send 审批内容统一；G5：docstring 修复
├── pktgen/adapter.py          # G3：_hitl_gate 统一；G4：env 默认值注入 + duration 钳制
├── trex/tools.py              # G3：_execute_live 审批内容统一 + 静态扫描非硬边界声明
├── tools/                     # G5：常量与 docstring 一致性核对（只读核对，按需修订）
├── prompts/system_prompt.j2   # G5：上限表与常量一致性核对
└── config/                    # 只读事实源（experiment.json / allowlist.json，不新增字段超出契约）

README.md                      # G1/G5：安全机制说明与风险声明同步
tests/unit/ · tests/integration/  # G6：门控矩阵/钳制/互斥/告警/契约一致性测试
```

**结构决策**: 横切特性无独立部署单元，不新增 src 目录；全部改动落在既有模块的安全边界处（main.py 入口校验、三处 interrupt 调用点、adapter 参数层），契约文档集中在 `contracts/` 供 001–007 引用。

## 实施阶段

- **阶段 0 · 研究**：产出 [research.md](research.md) —— 3 项澄清决议 + 钳制策略、上限定位、TRex 静态扫描定位等 3 项技术决策。
- **阶段 1 · 设计**：产出 [data-model.md](data-model.md)、[quickstart.md](quickstart.md)、[contracts/](contracts/)；完成后复查宪法检查（结论：仍全部满足）。
- **阶段 2 · 任务生成**：由 speckit-tasks 依据本计划产出 `tasks.md`（本步不创建）。

### 现状 → 规格差距（本计划的实际改动工作包）

| 编号 | 差距描述（现状 vs 规格） | 涉及文件 | 对应 FR/SC |
|------|------------------------|---------|-----------|
| G1 | 现状 --auto-approve 可与 --pktgen-live/--trex-live 组合，形成全自动真实流量；008-1 决议要求启动即报错退出 | src/main.py、tests/ | FR-017、SC-004 |
| G2 | 现状 experiment.json 默认值超上限被工具静默钳制，无提示；008-2 决议要求启动时检测并输出警告（列出超限项与钳制后值） | src/main.py、tests/ | FR-006/FR-020、SC-003 |
| G3 | 现状三处 HITL 审批内容字段不一（tools.py 两处 message+params；adapter._hitl_gate 附 mode；trex._execute_live 附 filename/code_preview/warning）；008-3 决议要求统一参数明细格式 | src/agent/tools.py、src/pktgen/adapter.py、src/trex/tools.py、contracts/hitl-payload.md | FR-008/FR-010、SC-004（展示层） |
| G4 | 现状 adapter @tool 默认值硬编码（rate=50.0、duration=5000），未读取 main.py 注入的 PKTGEN_RATE/PKTGEN_DURATION_MS（experiment.json pktgen.duration_ms=10000 与工具默认 5000 不一致）；duration 参数未显式钳制（仅 _wait_for_attack 等待封顶 60s，下发硬件的 duration 未限制） | src/pktgen/adapter.py、tests/ | FR-007/FR-013、SC-003/SC-005 |
| G5 | 现状工具 docstring 滞后（标称 max pps=200/duration=10s/packet_size=512/flow_count=50，实际常量 20000/20/1024/100）；需同步 docstring/系统提示/README 并加一致性测试 | src/agent/tools.py、src/prompts/system_prompt.j2、README.md、tests/ | FR-016、SC-008 |
| G6 | 测试与收敛：门控矩阵逐技能验证、钳制边界（等于上限/超上限）、互斥报错、告警输出、统一契约校验、文档一致性测试、SC-001~010 收敛矩阵 | tests/ | 宪法三/二、SC-001~010 |

## 复杂度追踪

> 仅当宪法检查存在需论证的违反时填写

无——宪法检查逐条通过，不存在需论证的违反项。
