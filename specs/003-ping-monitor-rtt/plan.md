# 实施计划：Ping 监控与 RTT 观测

**特性目录**: `specs/003-ping-monitor-rtt/` | **日期**: 2026-11-19 | **规格**: [spec.md](./spec.md)

**输入**: 来自 `specs/003-ping-monitor-rtt/spec.md` 的功能规格

## 摘要

为闭环实验的观测层制定**回溯式**实施计划：持续后台 ping 监控（fping -Q 双后端 + 系统 ping 跨平台回退）、攻击期间 RTT 观测对齐（attack_window / observation_window / rtt_during / covers_attack_window）与单次测量（allowlist 校验）的主体能力**已存在于代码库**（`src/tools/ping_monitor.py`、`rtt_window.py`、`ping_rtt_tool.py`）。本计划的工作内容不是从零实现，而是「现状 → 规格差距」的收敛改动：

- 按澄清默认（003-2 / 003-3）：探测节奏与样本缓冲上限从硬编码改为 `experiment.json` 统一配置、调用时读取（宪法「配置单一来源」）；
- 补齐生命周期清理缺口：Web 控制台结束实验时同样停止监控（FR-016）；
- 以测试固化跨语言丢包解析、加权统计口径、五类覆盖判定、并发安全与启停无残留（SC-002~SC-007）。

技术方案维持现状选型：fping -Q（10 探针/秒、每秒摘要、加权收发计数）优先，系统 ping（Windows/Unix 连续模式）回退；不引入新依赖。

## 技术上下文

**语言/版本**: Python 3.11+（uv 管理依赖）

**主要依赖**: 标准库（subprocess / threading / collections / re）；外部二进制 fping（Linux/macOS，可选，`PATH` 探测）与系统自带 ping；LangChain `@tool` 包装（`src/agent/tools.py`，本特性不产生攻击流量、无 HITL 门控）

**存储**: 内存有界样本缓冲（线程安全 deque，上限可配置、默认 4000 条，超出淘汰最旧）；无持久化（实验结果由 `log_tool` 写 JSONL，不属于本特性）

**测试**: pytest（`uv run pytest tests/unit/ -v`）；解析器与统计口径用构造输出行做纯单元测试，命令构造与子进程生命周期做集成测试

**目标平台**: Linux/macOS（fping -Q 主路径）、Windows（系统 ping 回退）；平台差异经运行时探测选择，不硬编码平台命令

**项目类型**: CLI 实验 + Web 控制台共用的内嵌工具集（`src/tools/`）

**性能目标**: 每秒 10 次探测（±1）、每秒 1 条摘要行；聚合/采样查询为窗口内线性扫描且不阻塞采集线程（SC-001 / SC-004）

**约束**: 线程安全；内存有界；跨平台；目标必须过 allowlist（非广播/组播/非法格式）；攻击时刻与样本时间戳同一时钟源可直接比较

**规模/范围**: 单一目标监控（v1，见澄清 003-1）；最长实验 ≈ 20 s × 20 轮 + Pktgen 最长 60 s 等待；单进程单例

## 宪法检查

*门禁：阶段 0 研究前必须通过；阶段 1 设计后复查。*

| 宪法原则 | 检查结论 |
|---------|---------|
| 一、先想清楚再动手（计划先行） | ✅ 满足。spec.md 已评审，本文件即第二步；tasks.md 由 speckit-tasks 生成后才进入 implement。 |
| 二、闭环驱动（全流程收敛） | ✅ 满足。本特性就是实验闭环的观测半环（攻击 → RTT 观测 → 决策）；covers_attack_window 保证每动作的观测回馈真实可信，converge 阶段将按 FR 复核。 |
| 三、测试伴随（新功能必配测试） | ✅ 满足（以实施为前提）。差距清单 G-004~G-007 每项配套单测/集成测试；现有 `tests/unit/test_ping_monitor.py`、`test_rtt_window.py`、`test_ping_rtt_tool.py` 需扩展覆盖。 |
| 四、安全优先（不可协商） | ✅ 满足。启动监控与单次测量均先经 `validate_target`（allowlist/格式/广播/组播），非法目标 100% 拒绝且不发探测；监控与测量不产生攻击流量，无 HITL 需求。 |
| 五、可观测驱动（数据说话） | ✅ 满足（核心原则）。本特性是该原则的实现载体：每个攻击动作附 `rtt_during` 与 `covers_attack_window`；监控未运行/无样本/全丢失/窗口过短时强制判定未覆盖并说明原因，未覆盖的观测不得作为决策依据。 |
| 六、配置单一来源 | ✅ 满足（以差距 G-001/G-002 实施为前提）。现状探测节奏与缓冲上限为硬编码常量，违反本原则；经澄清 003-2/003-3 采纳后改为 `experiment.json` → 环境变量 → 调用时读取，消除漂移。 |

阶段 1 设计后复查：无新增违反项；配置单一来源的整改已落入差距清单 G-001/G-002，其余原则在设计制品（data-model / contracts）中得到保持。

## 项目结构

### 文档（本功能）

```text
specs/003-ping-monitor-rtt/
├── plan.md              # 本文件（speckit-plan 产出）
├── research.md          # 阶段 0 产出（澄清采纳与技术决策）
├── data-model.md        # 阶段 1 产出（实体与状态流转）
├── quickstart.md        # 阶段 1 产出（端到端验证场景）
├── contracts/           # 阶段 1 产出
│   ├── monitor-sample.md      # MonitorSample 与查询接口 JSON 契约
│   └── rtt-observation.md     # build_rtt_observation 输出 JSON 契约
└── tasks.md             # 阶段 2 产出（speckit-tasks 产出，非本步）
```

### 源代码（仓库根）

```text
src/
├── tools/
│   ├── ping_monitor.py      # 现状：双后端/单例/线程安全 deque；改动：节奏与上限配置化（G-001/G-002）
│   ├── rtt_window.py        # 现状：build_rtt_observation；基本无改动，测试固化（G-005）
│   └── ping_rtt_tool.py     # 现状：单次测量 + allowlist；基本无改动，测试固化（G-007）
├── agent/tools.py           # 现状：3 个监控工具包装（异常已捕获）；改动：env 默认值透传
├── main.py                  # 现状：env 注入 + finally 清理；改动：注入 PING_MONITOR_* 环境变量
└── config/experiment.json   # 改动：新增 "ping_monitor" 配置节

backend/
└── experiment.py            # 改动：finally 补 monitor.stop()（G-003）

tests/
├── unit/test_ping_monitor.py    # 扩展：跨语言解析、加权口径、配置读取、并发（G-004/G-005/G-006）
├── unit/test_rtt_window.py      # 扩展：五类覆盖判定（G-005）
└── unit/test_ping_rtt_tool.py   # 扩展：拒绝路径（G-007）
```

**结构决策**: 保持现状模块边界——工具实现（`src/tools/`）与 LangChain 包装（`src/agent/tools.py`）分离、配置走既有流（experiment.json → main.py 设 env → 工具调用时读取）；不新增模块。Web 侧清理复用同一单例的 `stop()`，与 CLI 保持一致的生命周期语义。

## 实施阶段

- **阶段 0 · 研究**：产出 `research.md`。三个澄清项按推荐默认采纳（003-1 单目标、003-2 节奏入配置、003-3 缓冲上限可配置），并确认保持双后端与加权口径、明确测试策略。
- **阶段 1 · 设计**：产出 `data-model.md`、`quickstart.md`、`contracts/`（monitor-sample.md、rtt-observation.md）；完成后复查宪法检查（见上，无新增违反）。
- **阶段 2 · 任务生成**：由 speckit-tasks 依据本计划与差距清单产出 `tasks.md`（本步不创建）。

### 现状 → 规格差距清单（实施工作内容）

| 编号 | 关联 FR / SC | 现状 | 差距与改动 | 涉及文件 |
|------|-------------|------|-----------|---------|
| G-001 | FR-003、FR-009、SC-001（澄清 003-2） | fping -Q 节奏硬编码（`-p 100` / `-Q 1`）；回退间隔 1.0 s、聚合窗口 5.0 s 为函数默认参数 | `experiment.json` 新增 `"ping_monitor"` 节：`probes_per_sec=10`、`summary_interval_s=1`、`fallback_interval_s=1.0`、`stats_window_s=5.0`；main.py 注入 `PING_MONITOR_*` 环境变量；`start()` 与命令构造调用时读取 | `src/config/experiment.json`、`src/main.py`、`src/tools/ping_monitor.py` |
| G-002 | FR-006、SC-004（澄清 003-3） | `_MAX_SAMPLES = 4000` 类常量 | `max_samples`（默认 4000）入 `"ping_monitor"` 节，deque 上限构造时按配置确定 | 同上 |
| G-003 | FR-016 | CLI `main.py` finally 已 `stop()`；Web `backend/experiment.py` finally 未清理监控 | Web 实验结束路径（finally / stop 流程）调用 `get_ping_monitor().stop()`，保证 Web 模式无孤儿探测进程 | `backend/experiment.py` |
| G-004 | FR-005、SC-002 | 丢包解析覆盖英文模式与中文「请求超时」 | 以英文 + 中文输出样本集测试固化；必要时补中文不可达模式（如「无法访问目标主机」等） | `tests/unit/test_ping_monitor.py`、`src/tools/ping_monitor.py`（如需要） |
| G-005 | FR-013、SC-003 | 加权口径（收到数加权、loss=1−收/发）与观测构造五类判定已实现 | 测试固化：加权平均与丢失率口径、未运行/无样本/全丢失/窗口过短/正常覆盖五类判定 100% 符合预期 | `tests/unit/test_rtt_window.py`、`test_ping_monitor.py` |
| G-006 | SC-004、SC-006 | 无并发与启停残留测试 | 新增：10 线程并发查询一致性测试；连续 20 次启停无残留探测进程测试 | `tests/unit/`（新增用例） |
| G-007 | FR-002、FR-014、SC-005 | `validate_target` 已实现于启动与单次测量双入口 | 拒绝路径测试补齐：allowlist 外 / 广播 / 组播 / 非法格式，监控启动与单次测量均 100% 拒绝且零探测 | `tests/unit/test_ping_rtt_tool.py` 等 |

**现状已满足、无需改动**（仅由测试与 converge 复核）：FR-001 持续探测、FR-002 校验逻辑本体、FR-007 单例、FR-008 重启先停旧、FR-009/FR-010 窗口与采样查询、FR-011 观测构造、FR-012 覆盖判定、FR-014 单次测量、FR-015 失败结构化返回（`start_ping_monitor` 工具层已捕获异常并返回错误字典）。

## 复杂度追踪

> 仅当宪法检查存在需论证的违反时填写

无违反项：本计划不引入超出宪法原则的复杂度，无需论证。
