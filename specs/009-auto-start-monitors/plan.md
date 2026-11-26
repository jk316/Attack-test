# 实施计划：拨测监控生命周期收归程序

**特性目录**: `specs/009-auto-start-monitors/` | **日期**: 2026-11-20 | **规格**: [spec.md](spec.md)

**输入**: 来自 `specs/009-auto-start-monitors/spec.md` 的功能规格

## 摘要

把 ping（RTT）与 HTTP 后台拨测的生命周期从「Agent 调用 start/stop 工具」收归为「程序在实验开始时自动启动、退出时自动清理」。两个入口（CLI `src/main.py`、Web 控制台 `backend/experiment.py`）共用新的生命周期编排模块；Agent 工具集删除 4 个 start/stop 工具（23→19），只保留读取与单次探测；系统提示词与结果提示文案同步改为「监控由程序管理」。

## 技术上下文

**语言/版本**: Python ≥3.11（当前 venv 3.13.11）

**主要依赖**: LangChain/LangGraph（Agent 图与工具集）、FastAPI + WebSocket（后端）、Scapy、fping 或系统 ping（RTT 后端）、curl（HTTP 拨测）

**存储**: 文件（`data/agent.log`、`data/experiment.jsonl`）；本特性不新增存储

**测试**: pytest（`uv run pytest tests/unit/ tests/integration/`），标记 unit/integration/slow

**目标平台**: Linux 服务器（实验运行）+ macOS（开发）；ping 后端跨平台自适应（fping 优先，系统 ping 回退）

**项目类型**: CLI + Web 服务 + LangChain Agent 工具集

**性能目标**: 监控启动开销 < 1 秒；不增加实验轮次耗时；监控子进程在进程退出后 5 秒内回收

**约束**: allowlist 强制校验（FR-003）；HITL 门禁不适用于监控（观测行为）；监控参数上限与跨平台约定遵循宪法附加约束

**规模/范围**: 单进程单实验（两入口均有互斥）；改动面：1 个新模块 + 5 个源文件修改 + 3 个测试文件修改 + 1 个新测试文件

## 宪法检查

*门禁：阶段 0 研究前必须通过；阶段 1 设计后复查。*

| 宪法原则 | 结论 |
|----------|------|
| 一、先想清楚再动手 | ✅ spec.md（已批准）→ 本 plan → tasks，实现前全部就位 |
| 二、闭环驱动 | ✅ 本特性按 specify → plan → tasks → implement → converge 推进；特性本身强化「每轮必有观测回馈」 |
| 三、测试伴随 | ✅ R8：新增 `test_monitor_lifecycle.py` + 两处入口集成用例 + 工具数断言更新 |
| 四、安全优先 | ✅ FR-003：监控目标过 `validate_target`（allowlist）才启动；不触碰 HITL 门禁；无流量工具改动 |
| 五、可观测驱动 | ✅ 本特性目标即「观测数据每轮必有」，直接服务该原则 |
| 六、配置单一来源 | ✅ R2：后端与 CLI 同源读项目根 `experiment.json`；helper 不硬编码默认值 |
| 附加约束：跨平台 / 文档真实性 | ✅ 不新增 OS 特定逻辑；提示词与 note 文案同步（宪法点名 docstring 滞后问题，本次顺手修复 monitor 相关文案） |

**结论**: 无违反项，复杂度追踪不适用。

## 项目结构

### 文档（本功能）

```text
specs/009-auto-start-monitors/
├── plan.md              # 本文件（speckit-plan 产出）
├── research.md          # 阶段 0 产出
├── data-model.md        # 阶段 1 产出
├── quickstart.md        # 阶段 1 产出
├── contracts/
│   └── monitor-lifecycle.md   # 阶段 1 产出
├── checklists/
│   └── requirements.md  # speckit-specify 产出
└── tasks.md             # 阶段 2 产出（speckit-tasks 产出，非本步）
```

### 源代码（仓库根）

```text
src/
├── main.py                        # 改：预检/env 注入后自动启动；finally 扩展清理 HTTP
├── agent/
│   └── tools.py                   # 改：删 4 个 start/stop 工具；EXPERIMENT_TOOLS 19
├── tools/
│   ├── monitor_lifecycle.py       # 新：start/stop_experiment_monitors 编排
│   ├── rtt_window.py              # 改：note 文案「需先调用 start_ping_monitor」→ 新语义
│   └── http_window.py             # 改：同上
├── pktgen/
│   └── adapter.py                 # 改：docstring 文案同步
└── prompts/
    └── system_prompt.j2           # 改：协议第 0 步 / 工具表 / 错误指引

backend/
└── experiment.py                  # 改：start() 自动启动 + finally 清理

tests/
├── unit/
│   └── test_monitor_lifecycle.py  # 新：启动/清理/幂等/allowlist/失败降级
├── integration/
│   ├── test_agent_graph.py        # 改：23→19 断言 + 工具名断言
│   └── test_pktgen_integration.py # 改：23→19 断言
└── e2e/
    └── test_e2e_closed_loop.py    # 改：移除/改写 start 工具引用
```

**结构决策**: 编排模块放在 `src/tools/`，与两个 monitor 模块同层（导入成本低、职责清晰）；契约只写一份 `contracts/monitor-lifecycle.md`（生命周期 + 工具集 + 观测字段三节，避免碎片化）；不新建目录。

## 实施阶段

- **阶段 0 · 研究**：✅ 产出 `research.md`（R1~R8：编排位置、后端配置来源、启动/清理时机、工具移除范围、降级与幂等、文案同步、目录模式豁免、测试策略）。
- **阶段 1 · 设计**：✅ 产出 `data-model.md`、`contracts/monitor-lifecycle.md`、`quickstart.md`；宪法检查复查通过（见上表）。
- **阶段 2 · 任务生成**：由 speckit-tasks 依据本计划产出 `tasks.md`（本步不创建）。

## 复杂度追踪

> 仅当宪法检查存在需论证的违反时填写

无违反项。
