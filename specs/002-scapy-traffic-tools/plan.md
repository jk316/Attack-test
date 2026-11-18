# 实施计划：Scapy 流量工具集

**特性目录**: `specs/002-scapy-traffic-tools/` | **日期**: 2026-11-19 | **规格**: [spec.md](./spec.md)

**输入**: 来自 `specs/002-scapy-traffic-tools/spec.md` 的功能规格

## 摘要

本特性覆盖四个 Scapy 工具：`traffic_send`（单协议 UDP 流量）、`mixed_traffic_send`（多协议混合流量）、`ping_rtt`（单次 RTT 探测）、`log_result`（JSONL 实验日志），以及它们在 Agent 层的 `@tool` 封装与 HITL 门控。核心行为：参数钳制上限（pps=20000 / duration_s=20 / packet_size=1024 / flow_count=100 / iat_jitter_ms=20 / MAX_STREAMS=100）、allowlist 拒绝、多流轮转与抖动、JSON 规格白名单/百分比补全/目标 IP 覆盖/注入扫描、JSONL 日志。

本计划为**回溯式计划**：现有代码已实现绝大部分安全与发送行为。规格澄清项按推荐默认采纳后，与现状的差距为四处：**G1 钳制感知标注**（002-1：返回原请求值与「已钳制」标注）、**G2 混合工具抖动统一配置**（002-2）、**G3 发送中断标注**（002-3：标注「未完整发送」）、**G4 docstring 陈旧上限修复**（FR-018：200/10/512/50 → 20000/20/1024/100）；其余条目以测试与 JSON 契约锁定既有行为。

## 技术上下文

**语言/版本**: Python 3.11+

**主要依赖**: Scapy（报文构造与发送，`IP/TCP/UDP/ICMP/DNS/Raw`、`send`）、LangChain `@tool`（Agent 工具封装与 HITL `interrupt()`）、pytest、uv

**存储**: 文件——JSONL 实验日志（`log_result` 追加单行 JSON + UTC 时间戳）；allowlist 配置 `src/config/allowlist.json`

**测试**: pytest；`tests/unit/`（mock 全部 I/O，conftest 注入项目根）、`tests/integration/`（mock 网络）；测试 IP 约定：`10.99.80.160`（allowlist）、`192.168.1.99`（拒绝）

**目标平台**: Linux / macOS / Windows 跨平台（ping 命令按 `sys.platform` 选择参数，不硬编码）

**项目类型**: 库（`src/tools/` 四个工具函数）+ Agent 工具封装（`src/agent/tools.py`）

**性能目标**: 发送循环以钳制后速率尽力发包（≤20000 pps 上限约束）；`ping_rtt` 对可达目标 15 秒内返回（SC-007）

**约束**: 安全优先——allowlist 校验、禁止广播/组播/源 IP 伪造、HITL 审批不可绕过、注入模式扫描；上限常量单一来源（`src/tools/traffic_send_tool.py` 的 MAX_* 与宪法）

**规模/范围**: 4 个工具 + 2 个 HITL 门控封装；混合规格 1–100 流、JSON ≤10000 字符

## 宪法检查

*门禁：阶段 0 研究前必须通过；阶段 1 设计后复查。*

| # | 宪法原则 | 本计划如何满足 | 结论 |
|---|---------|--------------|------|
| 一 | 先想清楚再动手（计划先行） | 本计划即该原则执行；实施阶段全部来自规格差距清单，不扩张 | ✅ 满足 |
| 二 | 闭环驱动（全流程收敛） | 发送结果附带攻击窗口观测字段（FR-019），每轮行动必有回馈；截断标注（002-3）防止把不完整观测当作闭环依据 | ✅ 满足 |
| 三 | 测试伴随 | 每个差距项配套单元测试：钳制标注、抖动配置、截断标注、docstring 一致性；既有安全行为补测试锁定 | ✅ 满足 |
| 四 | 安全优先（不可协商） | allowlist/广播/组播/源伪造拒绝矩阵保持且补测试；HITL 门禁不变弱；002-1 标注只增加信息、不放松任何钳制 | ✅ 满足 |
| 五 | 可观测驱动（数据说话） | JSONL 日志含 UTC 时间戳；结果契约含 rtt_during/observation_window 对齐字段 | ✅ 满足 |
| 六 | 配置单一来源 | 抖动参数纳入 experiment.json（002-2），经 env 调用时读取；工具不硬编码与配置冲突的默认值 | ✅ 满足 |

**门禁结论**: 六条原则全部满足，无需要论证的违反项；「复杂度追踪」表无需填写。

*阶段 1 设计复查*: data-model（发送生命周期与校验规则）、quickstart、contracts（输入规格 + 四个工具 JSON 结果）均不引入新的宪法冲突，维持通过。

## 项目结构

### 文档（本功能）

```text
specs/002-scapy-traffic-tools/
├── spec.md              # 功能规格（speckit-specify 产出）
├── plan.md              # 本文件（speckit-plan 产出）
├── research.md          # 阶段 0 产出：澄清决策（002-1/2/3）与选型
├── data-model.md        # 阶段 1 产出：实体、校验规则、发送生命周期
├── quickstart.md        # 阶段 1 产出：端到端验证场景
├── contracts/
│   ├── traffic-spec-json.md   # 阶段 1 产出：混合流量输入规格契约
│   └── tool-result-json.md    # 阶段 1 产出：四个工具 JSON 结果契约
└── tasks.md             # 阶段 2 产出（speckit-tasks，非本步）
```

### 源代码（仓库根）

```text
src/
├── tools/
│   ├── traffic_send_tool.py    # UDP 发送 + validate_params + MAX_* 常量（上限单一来源）
│   ├── mixed_traffic_tool.py   # 混合发送 + validate_traffic_spec + 白名单/注入扫描
│   ├── ping_rtt_tool.py        # validate_target/allowlist 加载 + 单次 ping
│   └── log_tool.py             # JSONL 追加（UTC 时间戳）
├── agent/
│   └── tools.py                # @tool 封装：HITL 门控、env 默认值、观测字段合并（rtt_window）
├── config/
│   ├── experiment.json         # attack.iat_jitter_ms 等默认（002-2 落点）
│   └── allowlist.json          # 目标白名单
└── tools/
    └── rtt_window.py           # build_rtt_observation（003 规格，本特性仅引用）

tests/
├── unit/                       # 参数钳制/校验拒绝/规格校验/日志行为（mock 全部 I/O）
└── integration/                # mock 网络上的发送循环与轮转行为
```

**结构决策**: 保持「行为常量在 `src/tools/*_tool.py`、Agent 封装在 `src/agent/tools.py`」的现状分层；钳制标注（G1）与截断标注（G3）在工具函数层实现（返回结构变更），@tool 层透传并合并观测字段；docstring 修复（G4）落在 `src/agent/tools.py` 的 `@tool` 描述，系统提示（system_prompt.j2）已为正确值无需改。契约文件是本特性的对外权威，实施与测试均据此核对。

## 实施阶段

- **阶段 0 · 研究**：产出 `research.md`。调研项：钳制标注结构（002-1）、抖动统一配置方案（002-2）、截断标注结构（002-3）、上限常量权威来源与 docstring 修复方式、通道降级顺序确认。
- **阶段 1 · 设计**：产出 `data-model.md`（实体/校验规则/发送生命周期）、`quickstart.md`、`contracts/traffic-spec-json.md` 与 `contracts/tool-result-json.md`；完成后复查宪法检查（已复查通过）。
- **阶段 2 · 任务生成**：由 speckit-tasks 依据本计划产出 `tasks.md`（本步不创建）。

### 实施工作清单（现状 → 规格差距）

> 回溯式：现状以源码为准（src/tools/{traffic_send,mixed_traffic,ping_rtt,log}_tool.py、src/agent/tools.py）。

| 编号 | 差距项 | 现状 | 目标（规格/澄清决策） |
|------|--------|------|----------------------|
| G1 | 钳制感知标注（002-1） | 只返回钳制后的 `params`，模型无法感知被钳制 | 结果增加 `requested_params`（原请求值）与 `clamped` 标注（逐字段），明确「已钳制」信息（FR-004） |
| G2 | 混合工具抖动统一配置（002-2） | `mixed_traffic_send` 固定 ±20ms 抖动且无抖动参数；`traffic_send` 已支持 0–20ms 可配置（env ATK_IAT_JITTER_MS） | `mixed_traffic_send` 增加 `iat_jitter_ms`（默认读 env、钳制 0–20），替换固定抖动；系统提示参数表同步（FR-014） |
| G3 | 发送中断标注（002-3） | Ctrl-C 静默停止并返回已发送统计，无标记 | 结果增加 `completed=false` + `interrupt_reason`，标注「未按计划完整发送」（FR-008） |
| G4 | docstring 陈旧上限修复（FR-018） | `src/agent/tools.py` 的 @tool 描述写 max pps=200/duration=10/packet_size=512/flow_count=50 | 修正为 20000/20/1024/100（与常量/宪法一致）；system_prompt.j2 已正确，核对即可 |
| G5 | 既有安全行为测试锁定 | allowlist 拒绝、广播/组播/源伪造、HITL 拒绝 0 报文、轮转、百分比补全、注入扫描均已实现但测试覆盖需确认 | 按 SC-001–005 补单元/集成测试（行为不变，测试伴随） |
| G6 | 结果契约一致性 | 四工具返回结构与契约文档无权威对照 | 以 contracts/tool-result-json.md 为准核对实现并补契约测试（FR-008/015/016/019） |
| G7 | ping/log 行为锁定 | `ping_rtt` 全丢包 inf、超时/命令缺失失败；`log_result` 目录缺失失败均已实现 | 补测试锁定（SC-007/008），不改变行为 |

## 复杂度追踪

> 仅当宪法检查存在需论证的违反时填写

宪法检查逐条通过，无违反项，本表不适用。
