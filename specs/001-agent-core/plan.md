# 实施计划：核心闭环 ReAct Agent 与运行模式

**特性目录**: `specs/001-agent-core/` | **日期**: 2026-11-19 | **规格**: [spec.md](./spec.md)

**输入**: 来自 `specs/001-agent-core/spec.md` 的功能规格

## 摘要

本特性为闭环网络实验 Agent 的核心运行时：统一构建入口按模式（实验 / 目录探索）选择系统提示与工具集，支撑 CLI 实验、CLI 目录探索、Web 控制台三种运行形态；多轮对话保留 DeepSeek 推理内容；收敛早停（no_improve_limit 连续无改善即停）与 max_iters 预算双重控制运行终点；CLI 入口负责参数注入与 HITL 审批轮询。

本计划为**回溯式计划**：现有代码已实现大部分能力（三模式构建、reasoning_content 补丁、HITL 轮询、env 注入链、profiles）。规格澄清项按推荐默认采纳后，与现状的差距集中在三处：**G1 收敛早停运行时硬裁决**（现状仅为提示词软约束）、**G2 奖励公式统一**（提示与运行时状态模块公式不一致）、**G3 启动前预检**（现状无预检）；其余条目以测试与契约文档锁定既有行为。

## 技术上下文

**语言/版本**: Python 3.11+（`pyproject.toml` 注册 unit/integration/slow pytest 标记）

**主要依赖**: LangChain（`create_agent`、`ChatOpenAI`）、LangGraph（StateGraph、MemorySaver 检查点、`interrupt()`/`Command` 人机交互）、Jinja2（系统提示模板）、DeepSeek API（OpenAI 兼容端点）、FastAPI（Web 控制台宿主，本特性仅约束契约）、uv（依赖与运行管理）

**存储**: 文件——`data/experiment.jsonl`（实验结果日志）、`data/agent.log`（LLM I/O 完整日志）、`output/trex_attack_catalog_<时间戳>.md`（目录探索摘要）；MemorySaver 内存检查点（进程内，不跨进程持久化）

**测试**: pytest；`tests/unit/`（mock 全部 I/O，conftest 注入项目根到 sys.path）、`tests/integration/`（真实编译器 + mock 网络）、`tests/e2e/`（完整 Agent 循环）

**目标平台**: Linux / macOS / Windows 跨平台（一律 `sys.platform` 检测，不硬编码 OS 标志）

**项目类型**: CLI 应用 + Web 服务混合（本特性聚焦 CLI 入口与统一构建契约）

**性能目标**: 本地构建阶段（不依赖模型响应）在 10 秒内完成并发起首个模型请求（SC-001）

**约束**: 安全优先（HITL 门禁不可绕过、无终端输入默认拒绝）、配置单一来源（experiment.json → env → 调用时读取）、互斥参数启动即报错（--trex-explore × --trex-live）

**规模/范围**: 19 个工具（8 Scapy + 9 Pktgen + 2 TRex）；单次运行 max_iters 默认 20、目录探索默认 40；单进程单实验运行

## 宪法检查

*门禁：阶段 0 研究前必须通过；阶段 1 设计后复查。*

| # | 宪法原则 | 本计划如何满足 | 结论 |
|---|---------|--------------|------|
| 一 | 先想清楚再动手（计划先行） | 本计划即该原则的执行；实施阶段全部工作均源自规格差距清单，不扩张范围 | ✅ 满足 |
| 二 | 闭环驱动（全流程收敛） | 001-1 运行时硬裁决保证闭环有确定终点；每轮「行动→观测→记录→决策」有观测回馈（FR-002） | ✅ 满足 |
| 三 | 测试伴随 | 每个差距项配套测试：硬裁决确定性序列测试（SC-003）、补丁多轮回归（SC-002）、预检单测（G3）、注入链优先级测试（SC-005） | ✅ 满足 |
| 四 | 安全优先（不可协商） | HITL 门禁保持不可绕过；001-3 增加启动预检（目标 ∈ allowlist、预算为正）提前拦截违规输入；默认拒绝语义不弱化 | ✅ 满足 |
| 五 | 可观测驱动（数据说话） | LLM I/O 日志（FR-013）、实验 JSONL 日志、运行结束监控进程清理（SC-007）；奖励判定基于工具实测 RTT/丢包而非模型自述 | ✅ 满足 |
| 六 | 配置单一来源 | 早停预算与攻击参数经 experiment.json → env → 工具调用时读取；profiles 深合并保持单一文件 | ✅ 满足 |

**门禁结论**: 六条原则全部满足，无需要论证的违反项；「复杂度追踪」表无需填写。

*阶段 1 设计复查*: data-model（运行状态机）、quickstart（端到端验证）、contracts/cli-parameters.md（参数优先级链与互斥规则）均不引入新的宪法冲突，维持通过。

## 项目结构

### 文档（本功能）

```text
specs/001-agent-core/
├── spec.md              # 功能规格（speckit-specify 产出）
├── plan.md              # 本文件（speckit-plan 产出）
├── research.md          # 阶段 0 产出：澄清决策（001-1/2/3）与技术选型
├── data-model.md        # 阶段 1 产出：运行生命周期与状态实体
├── quickstart.md        # 阶段 1 产出：端到端验证场景
├── contracts/
│   └── cli-parameters.md  # 阶段 1 产出：CLI 参数契约
└── tasks.md             # 阶段 2 产出（speckit-tasks，非本步）
```

### 源代码（仓库根）

```text
src/
├── main.py                    # CLI 入口：参数解析、env 注入、HITL 轮询、LLM I/O 日志、清理
├── agent/
│   ├── graph.py               # build_graph：模式选择、模型构建、reasoning_content 补丁
│   ├── state.py               # 运行状态定义、奖励计算、停止条件（硬裁决复用点）
│   └── tools.py               # 19 个 @tool 封装与 HITL 门控
├── prompts/
│   ├── system_prompt.j2       # 实验模式系统提示（含停止条件与奖励公式）
│   └── trex_catalog_prompt.j2 # 目录探索模式提示
├── config/
│   ├── experiment.json        # 配置单一来源（max_iters/no_improve_limit/attack/pktgen/trex/profiles）
│   └── allowlist.json         # 允许目标清单
├── tools/                     # Scapy 工具集（详见 002 规格）
├── pktgen/ trex/ llm/         # 硬件加速与独立 LLM 包装（分别见 005/006 规格；llm/ 非运行时路径）
backend/                       # Web 控制台宿主（见 007 规格，本特性仅约束构建契约）
tests/
├── unit/                      # mock 全部 I/O：裁决、预检、注入链、提示渲染
├── integration/               # 真实编译器 + mock 网络
└── e2e/                       # 完整 Agent 循环
```

**结构决策**: 维持现有分层——`src/agent/` 承载构建与状态逻辑、`src/main.py` 承载 CLI 编排。硬裁决复用 `src/agent/state.py` 已存在但未接入主循环的 `check_stop_condition` / `update_best` / `compute_reward`（G1 改动集中在此处与 main.py 循环层）；启动预检（G3）放入 `main()` 构建图之前；奖励公式统一（G2）需同步修改 `system_prompt.j2` 与 `state.py` 两处文本，保持单一口径。

## 实施阶段

- **阶段 0 · 研究**：产出 `research.md`。调研项：收敛早停裁决机制（001-1）、奖励公式统一（001-2）、启动预检位置与报错方式（001-3）、reasoning_content 补丁评估、硬裁决的观测数据来源与目录模式豁免。
- **阶段 1 · 设计**：产出 `data-model.md`（运行生命周期状态机与实体）、`quickstart.md`（端到端验证）、`contracts/cli-parameters.md`（CLI 参数契约）；完成后复查宪法检查（已复查通过）。
- **阶段 2 · 任务生成**：由 speckit-tasks 依据本计划产出 `tasks.md`（本步不创建）。

### 实施工作清单（现状 → 规格差距）

> 回溯式：现状以源码为准（src/main.py、src/agent/graph.py、src/agent/state.py、src/prompts/system_prompt.j2）。

| 编号 | 差距项 | 现状 | 目标（规格/澄清决策） |
|------|--------|------|----------------------|
| G1 | 收敛早停硬裁决 | 停止条件仅写入提示词（软约束）；state.py 的 `check_stop_condition`/`update_best`/`compute_reward` 未接入主循环 | 运行时每轮以工具实测 RTT/丢包计算奖励并计数，达标强制终止（FR-006 + 001-1） |
| G2 | 奖励公式统一 | 提示 `reward = avg_rtt_ms + loss_pct×10` 与 state.py `avg − loss×0.1` 不一致 | 全链路统一为单一公式（FR-016 + 001-2），提示与运行时一致 |
| G3 | 启动前预检 | 不预检；非法目标/非正预算在首次工具调用才暴露 | 构建图前校验 target ∈ allowlist、max_iters/no_improve_limit 为正整数，不合规非零退出并说明（FR-017 + 001-3） |
| G4 | reasoning_content 多轮补丁 | 已实现（graph.py 双向 monkey-patch） | 保持现状；补多轮 ≥3 轮无 400 的回归测试（FR-009 / SC-002） |
| G5 | HITL 轮询与默认拒绝 | 已实现（poll interrupts + input + --auto-approve + EOF 拒绝） | 保持现状；补拒绝 0 报文、EOF 默认拒绝测试（FR-004/005 / SC-004） |
| G6 | 三模式构建契约 | 已实现（build_graph mode=experiment/catalog） | 保持现状；以契约文档 + e2e 验证目录模式 0 流量 0 审批（FR-001/011/012 / SC-006） |
| G7 | 配置注入链与 profiles | 已实现（experiment.json → env → 调用时读取；profiles 深合并） | 保持现状；补 CLI > profile > config > 内置默认优先级测试（FR-007/008/015 / SC-005/008） |
| G8 | LLM I/O 日志与清理 | 已实现（VerboseCallback → 控制台 + data/agent.log；finally 停监控） | 保持现状；补无残留监控进程测试（FR-013/014 / SC-007） |

## 复杂度追踪

> 仅当宪法检查存在需论证的违反时填写

宪法检查逐条通过，无违反项，本表不适用。
