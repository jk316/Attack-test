# 实施计划：Web 控制台（实时实验监控与人工审批）

**特性目录**: `specs/007-web-console/` | **日期**: 2026-11-19 | **规格**: [spec.md](spec.md)

**输入**: 来自 `specs/007-web-console/spec.md` 的功能规格

## 摘要

为闭环实验 Agent 提供浏览器端控制台：实时消息流（AI 消息/工具结果/生命周期状态）、HITL 人工审批闭环（弹窗 → 批准/拒绝 → 队列回填 → 实验继续/中止）、PCAP 上传、实验状态查询与启停。**本仓库已存在一版实现**（backend/server.py、backend/experiment.py、frontend 三件套），因此本计划采用**回溯式**组织：技术上下文记录现有技术栈，实施阶段的工作内容 = 「现状 → 规格差距」的改动清单，而非从零搭建。

主要差距（详见「实施阶段」）：单客户端会话模型重构（G2）、PCAP 上传服务端校验（G3）、启动参数默认值接入配置单一来源（G4）、前端状态与展示完善（G5）、内网限定声明（G1）、测试补齐（G6）。规格中的 3 项 [需要澄清] 已按 Lead 决议采纳：仅限可信内网（无认证）、单客户端会话模型、上传服务端强制类型/大小校验——决议记录见 [research.md](research.md)。

## 技术上下文

**语言/版本**: 后端 Python 3.11+；前端原生 ES2020 JavaScript（无构建步骤、无框架）

**主要依赖**: FastAPI（WebSocket + REST + StaticFiles）、uvicorn、LangGraph（CompiledStateGraph.ainvoke / interrupt / Command(resume)）、LangChain 消息对象；前端 vanilla JS（fetch + WebSocket API）

**存储**: 文件系统（PCAP 上传 `data/uploads/`、实验日志 `data/experiment.jsonl`）；实验运行状态为进程内内存（不持久化、重启即失）

**测试**: pytest（`tests/unit/`、`tests/integration/` 既有目录；backend/ 当前无专项测试——本计划补齐）；前端无测试框架

**目标平台**: 服务端跨平台（Linux/macOS/Windows）；前端为桌面浏览器（Chromium/Firefox/Safari 现代版本）

**项目类型**: Web 服务（单机部署的本地实验控制台）

**性能目标**: SC-001 连接确认 <1s；SC-002 消息延迟 <500ms；SC-003 审批往返各 <1s；SC-008 状态查询 99.9% <100ms（单实验规模，非多租户）

**约束**: 仅限可信内网（无认证，声明式——007-1 决议）；HITL 门禁不可绕过（Web 端不提供任何自动批准入口）；单客户端会话模型（每 client_id 独立实验会话——007-2 决议）；跨平台（沿用 `sys.platform` 约定，前端无此问题）

**规模/范围**: 1 个服务进程 + 少量并发浏览器客户端；同一 client_id 同一时刻至多一个实验；v1 不做移动端适配、不做富文本渲染

## 宪法检查

*门禁：阶段 0 研究前必须通过；阶段 1 设计后复查。*

| 宪法原则 | 评估 | 结论 |
|---------|------|------|
| 一、先想清楚再动手（计划先行） | 本 plan.md 与设计制品（research/data-model/contracts/quickstart）先行，不直接进入编码 | 满足 |
| 二、闭环驱动（全流程收敛） | 实施阶段 G6 设收敛工作包：按 FR-001~020 / SC-001~010 逐项对照现状代码，剩余偏差追加为任务直至收敛 | 满足 |
| 三、测试伴随（新功能必配测试） | G6 为所有新增后端逻辑配单元测试（消息转换、HITL 队列、上传校验、会话互斥）与集成测试（WS 往返、状态查询）；前端逻辑以 quickstart 手工验收场景覆盖（前端测试基建引入与否见 research.md 决策 5） | 满足 |
| 四、安全优先（不可协商） | HITL 门禁不可绕过是核心约束：审批决定的唯一入口是操作员点击「批准/拒绝」按钮 → hitl_response → 队列回填 → Command(resume)；服务端不存在任何自动批准路径；拒绝 = 中止该次发送（FR-013/FR-014、SC-004/SC-005）。上传校验（类型/大小）防资源滥用（G3） | 满足 |
| 五、可观测驱动（数据说话） | 本特性是观测的**呈现层**（消息流/工具结果实时可见），不改动 RTT 采集本身（属 003-ping-monitor-rtt）；呈现层不得截断或篡改工具结果中的观测字段 | 满足 |
| 六、配置单一来源 | 启动参数默认值必须取自 experiment.json（当前 server.py/frontend 硬编码默认值 → 差距 G4）；本特性不新增第二份配置文件 | 满足 |

**结论**: 七项原则全部满足，无需要论证的违反项。阶段 1 设计完成后已复查（见 research.md 决策 6 与 data-model.md 的一致性说明）。

## 项目结构

### 文档（本功能）

```text
specs/007-web-console/
├── spec.md               # 功能规格（speckit-specify 产出）
├── plan.md               # 本文件（speckit-plan 产出）
├── research.md           # 阶段 0 产出（澄清决议 + 技术决策）
├── data-model.md         # 阶段 1 产出（实体/字段/校验/状态流转）
├── quickstart.md         # 阶段 1 产出（端到端验证场景）
├── contracts/            # 阶段 1 产出
│   ├── ws-messages.md    # WebSocket 消息契约（双向）
│   └── rest-api.md       # REST API 契约（上传/状态/启停）
└── tasks.md              # 阶段 2 产出（speckit-tasks 产出，非本步）
```

### 源代码（仓库根）

```text
backend/
├── server.py             # 差距 G1/G3/G4：上传校验、默认值注入、声明
└── experiment.py         # 差距 G2：per-client_id 会话注册表重构

frontend/
├── index.html            # 差距 G4/G5：表单默认值、声明横幅
├── app.js                # 差距 G4/G5：默认值拉取、启动被拒复位、摘要渲染
└── style.css             # 差距 G5：横幅/提示样式（少量）

tests/
├── unit/                 # 新增 backend 单测（消息转换、会话互斥、上传校验）
└── integration/          # 新增 WS 往返与状态查询集成测试
```

**结构决策**: 沿用现状目录（backend/ + frontend/ 静态三件套），不引入新模块目录。会话模型重构在 backend/ 内部完成（ExperimentManager 改造为 per-client_id 会话注册表），避免把实验编排逻辑拆散到新包；前端保持无构建步骤（static 直出），默认值通过新增只读接口拉取（见 research.md 决策 6）。

## 实施阶段

- **阶段 0 · 研究**：产出 [research.md](research.md) —— 3 项澄清决议 + 会话重构粒度、前端测试策略、默认值来源等 3 项技术决策。
- **阶段 1 · 设计**：产出 [data-model.md](data-model.md)、[quickstart.md](quickstart.md)、[contracts/](contracts/)；完成后复查宪法检查（结论：仍全部满足）。
- **阶段 2 · 任务生成**：由 speckit-tasks 依据本计划产出 `tasks.md`（本步不创建）。

### 现状 → 规格差距（本计划的实际改动工作包）

| 编号 | 差距描述（现状 vs 规格） | 涉及文件 | 对应 FR/SC |
|------|------------------------|---------|-----------|
| G1 | 无任何「仅限可信内网」声明；007-1 决议要求文档化声明 + 控制台可见提示 | README.md、frontend/index.html、server 启动日志 | FR-001（范围声明）、假设节 |
| G2 | 现状为进程级单例 ExperimentManager：所有客户端共享一个实验、任一客户端可审批/停止；007-2 决议改为每 client_id 独立实验会话（审批与停止绑定会话所有者，同会话互斥） | backend/experiment.py、backend/server.py | FR-002/FR-009/FR-010/FR-011/FR-013 |
| G3 | 现状上传仅前端限制扩展名，服务端不校验类型与大小；007-3 决议要求服务端强制扩展名白名单 + 大小上限（100MB）+ 结构化错误响应 | backend/server.py、tests/ | FR-015/FR-016、SC-010 |
| G4 | 现状 server.py `StartRequest` 与前端表单硬编码默认值（target_ip=10.99.80.160 等），与 experiment.json 不一致；宪法六要求默认值单一来源 | backend/server.py（新增只读默认值接口）、frontend/app.js、index.html | FR-008、宪法六 |
| G5 | 现状前端：启动被拒后仍显示「运行中」；experiment_done 不渲染摘要；状态栏「当前轮次/最佳 RTT/最近 RTT」无数据源常显 "-"；断线后无重连引导 | frontend/app.js、index.html | FR-006/FR-007/FR-009、SC-006/SC-007 |
| G6 | backend 无任何测试（宪法三）；补单元测试（_msg_to_dict、会话互斥、HITL 队列单次消费、上传校验）+ 集成测试（WS 往返、状态查询）+ SC 收敛验证 | tests/unit/、tests/integration/ | 宪法三、SC-001~010 |

## 复杂度追踪

> 仅当宪法检查存在需论证的违反时填写

无——宪法检查逐条通过，不存在需论证的违反项。
