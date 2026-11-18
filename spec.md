# 攻防智能体 Web 控制台 — 需求与设计规格（Spec）

> 状态：**v0.2（已评审 + 全部决策闭环，可进入实施）**
> 目标分支：`webui`
> 定位：把现有的「单次、单屏」Web 控制台，升级为「**实验为中心**」的攻防演练控制台——可配置创建、可实时观察、可历史回看。

---

## 1. 背景与目标

当前 Web 控制台（`backend/server.py` + `backend/experiment.py` + `frontend/`）只是最小可用雏形：

- 只支持**单个**正在运行的实验（`ExperimentManager` 内部单 `_graph` + 单 `_running` 标志）；
- 前端只有一个「消息流」面板 + 一个固定配置表单；
- 无历史持久化——刷新页面 / 进程重启后，实验记录全部丢失；
- 智能体的**思考过程（DeepSeek `reasoning_content`）**和**RTT 拨测成功率**都没有被显式提取和展示。

本规格的目标是把它改造成一个完整的攻防演练控制台，核心能力：

1. **创建实验**：通过表单配置一次攻防测试（目标、提示词、工具开关、参数上限、业务 PCAP）。
2. **实时观察**：运行中实时展示攻击类型、攻击大小、智能体推理过程、RTT 拨测指标。
3. **历史回看**：把每一次实验当作一条可查询、可回放的历史记录保存下来。

> 关键设计原则：**把「实验」（一次从创建到结束的攻防测试）作为一等公民实体**，前端围绕「实验列表 → 新建实验 → 运行详情 → 历史回看」这条主线组织；后端把"实验配置、运行状态、推理流、攻击事件、RTT 指标"统一持久化。

## 2. 术语表

| 术语 | 含义 |
|------|------|
| **实验（Experiment / Run）** | 一次从创建到结束的攻防测试。有唯一 `run_id`、配置、状态、结果摘要。 |
| **攻击（Attack）** | 实验中一次「产生流量」的工具调用（如 `traffic_send`、`pktgen_udp_flood`、`run_python_file` 实发）。 |
| **攻击类型（Attack Type）** | 本次攻击使用的工具 / 协议类型（UDP Flood、TCP SYN Flood、混合流量、Pktgen 线速泛洪、TRex 脚本等）。完整映射见 §8.8。 |
| **攻击大小（Attack Size / Intensity）** | 把不同工具的参数归一化后的"攻击强度"（详见 §8.5）。 |
| **推理过程（Reasoning Trace）** | 智能体每一步的：LLM 思考（`reasoning_content`）→ 文本输出 → 工具调用 → 工具结果 → HITL 审批 的完整时序。 |
| **拨测（Probe）** | 后台 `PingMonitor` 对目标 IP 的持续 ICMP 探测（`fping -Q` 或系统 `ping`）。 |
| **拨测成功率（Probe Success Rate）** | `收到探测数 / 发送探测数 × 100%`，即 `100% − loss_pct`。 |
| **HITL** | Human-in-the-loop 人工审批门控，所有流量工具在实发前暂停等待操作员批准。 |

## 3. Non-goals（本次明确不做）

- 不做**鉴权 / 多用户 / 权限**（任何能访问端口的人都能操作；默认绑定本机使用）。
- 不做**多实验并发执行**（同一时刻只跑一个，见 §8.2 状态机与排队）。
- 不做**移动端**适配（按桌面浏览器设计）。
- 不做 v1 的 **LLM 自动生成思考摘要**（用"截断摘要"，规则见 §10.4；LLM 总结留作可选增强）。
- 不做**系统级强制 `max_iters`/`no_improve_limit` 轮数**（现状是提示词约束，由 LLM 自行遵守；系统侧只做"无工具调用即自然结束"的判定，详见 §8.7 停止原因说明）。
- 不做数据库管理界面 / 实验数据导出工具（SQLite 文件可直接备份）。
- 不量化 **TRex 攻击大小**的精确 BPS/PPS（降级为脚本名 + 耗时，见 §8.5）。
- 不做容器化 / 多机部署（单机 FastAPI + SQLite）。

## 4. 现状盘点（已有能力 vs 缺口）

### 4.1 已有、可直接复用

| 能力 | 位置 | 说明 |
|------|------|------|
| 19 个工具（8 Scapy + 9 Pktgen + 2 TRex） | `src/agent/tools.py`、`src/pktgen/adapter.py`、`src/trex/tools.py` | 已注册，HITL/allowlist 已接好 |
| 后台拨测 + 丢包/成功率 | `src/tools/ping_monitor.py` | `get_stats()` 已返回 `sent_count/received/loss_pct`，成功率 `= 1 − loss_pct` |
| RTT 观测窗口 | `src/tools/rtt_window.py` | `rtt_during` + `attack_window` + `observation_window` 已在每个流量工具结果里 |
| DeepSeek 思考内容 | `src/agent/graph.py` `_patch_reasoning_content` | `reasoning_content` 已存入 `AIMessage.additional_kwargs` |
| WebSocket 实时流 + HITL | `backend/experiment.py` | `start/approve/stop`、`hitl_request/hitl_response` 已可用 |
| PCAP 上传 | `backend/server.py` `/api/upload/pcap` | 已实现 |
| 参数上限常量 | `src/tools/traffic_send_tool.py` | `MAX_PPS=20000`、`MAX_DURATION_S=20`、`MAX_PACKET_SIZE=1024`、`MAX_FLOW_COUNT=100`、`MAX_IAT_JITTER_MS=20` |

### 4.2 关键缺口（本规格要解决）

1. **无历史持久化**：`MemorySaver` 内存检查点，进程重启即丢；`log_tool` 是**LLM 驱动**的 JSONL（LLM 不一定调它，不可靠），不能作为系统级历史。
2. **单实验约束**：`ExperimentManager` 全局单实例、单 `_graph`、单 `_running`；且 `PingMonitor` 是单例、同一时刻只测一个 IP。→ 需明确"一次只跑一个 + 排队"的模型。
3. **思考过程被丢弃**：`experiment.py::_msg_to_dict` 只取 `role/content/tool_calls`，`additional_kwargs["reasoning_content"]` 被丢掉。
4. **工具不可选**：`build_graph()` 使用固定 `EXPERIMENT_TOOLS`，无法按实验勾选工具子集。
5. **参数上限不可配**：上限是模块级常量 + 环境变量默认值，无法在创建实验时按场景调整。
6. **"攻击大小 / 成功率"无统一定义**：前端统计面板（最佳 RTT / 最近 RTT）目前**根本没接线**，恒显示 `-`。
7. **无断线重连 / 页面刷新恢复**：刷新页面即失去运行中的实验上下文。
8. **同步工具阻塞事件循环**：`ainvoke` 内的工具是同步阻塞的（发包 pacing、`_wait_for_attack` 最长 60s），会卡住 WS 心跳与停止请求——P2 需把工具执行放到 executor（见 §13）。

---

## 5. 总体设计

### 5.1 前端信息架构（四条主线）

```
控制台
├── ① 实验列表页（默认首页）
│      └── 历史实验表格/卡片 + 「新建实验」按钮
├── ② 新建实验页（表单）
│      └── 5 项配置（见 FR-2） → 点击「开始测试」
├── ③ 实验运行/详情页（实时 + 历史回看共用）
│      ├── 攻击类型 / 攻击大小（每次攻击的卡片）
│      ├── 智能体推理过程（时序流）
│      └── RTT 拨测指标（成功率 + RTT 双轴曲线）
└── ④ HITL 审批（弹窗，嵌入详情页）
```

### 5.2 后端数据流

```
新建实验表单
   │  POST /api/experiments（校验 allowlist / 上限 / API key / PCAP）
   ▼
ExperimentManager.create(config) ──► 持久化 experiment(status=queued|running)
   │                                     │
   │  WS /ws/{run_id}                    │ 每步事件回调（权威流水）
   ▼                                     ▼
graph.ainvoke()  ──► 事件流（reasoning / tool_call / tool_result / hitl / status / error）
                          │
                          ├──► 实时推给前端（WS）
                          └──► 追加写 events 表（seq 自增，见 §8.3）
                                  └─► 同步抽取派生表：attacks（流量工具）/ probes（1s 聚合）
实验结束 ──► 一次性计算 experiments.summary（§8.7）──► status=completed/stopped/error
```

> 关键：**事件先写 `events`（权威流水），再推 WS**；`attacks`/`probes` 是**派生物化表**，只为查询快，永远可由 `events` 重建。

### 5.3 实验状态机

```
                   POST /api/experiments
                           │
        当前有实验在跑？ ──是──►  queued（排队中）
           │否
           ▼
        running ──────────────► completed（智能体自然结束）
           │  ▲                    stopped（用户手动停止）
           │  │                    error（异常 / LLM 失败）
           │  └── queued 队首在前一个结束后自动启动（FIFO）
           │
服务端进程重启 ──► running/queued 全部批量标记 interrupted（启动时一次性清理）
```

删除约束：

- `queued`/`running` **不允许删除**（须先取消/停止）；
- `completed`/`stopped`/`error`/`interrupted` 可**软删除**（置 `deleted_at`，见 §8.3）；
- `interrupted` 的实验可"重新开始"（复制配置新建一条实验）。

---

## 6. 功能需求（FR + 验收标准 AC）

> 格式：FR-x 为需求，AC 用 Given / When / Then 描述可验证的验收标准。测试与代码应能逐条追溯到这些编号。

### FR-1 实验历史列表

- 展示所有未软删除的实验，每行含：实验 ID（短 id）、目标 IP、状态徽章、创建时间、结果摘要（最终 RTT、拨测成功率、攻击次数、停止原因）。
- 状态徽章取值：`运行中 / 排队中 / 已完成 / 已停止 / 失败 / 中断`。
- 支持按状态过滤、按时间倒序（默认）、分页；列表页每 5s 轮询 `GET /api/experiments` 刷新状态与摘要。

**AC**
1. Given 库中存在 N 条未删除实验，When 打开首页，Then 按 `created_at` 倒序分页显示，每行字段齐全。
2. Given 列表页，When 选择状态过滤（六态之一），Then 只显示该状态的行。
3. Given 某实验被软删除，When 刷新列表，Then 该行消失。
4. Given 一条 running 实验在服务端结束，When 前端 5s 轮询，Then 该行状态与摘要自动更新。

### FR-2 创建新实验（表单，5 项配置）

| # | 配置项 | 说明 | 默认值来源 |
|---|--------|------|-----------|
| 1 | **攻击 IP** | 下拉框给出 `allowlist.json` 的 `hosts[]`，允许手动输入但后端强校验 | `allowlist.json` |
| 2 | **用户提示词** | 自由文本，描述本次实验目标/方向，注入 user message 与 system prompt | 空 |
| 3 | **攻击工具上限** | 每实验**软上限**（≤ 硬上限常量，硬上限不可下放）：pps、duration_s、packet_size、flow_count、pktgen rate、pktgen duration 等 | `experiment.json` |
| 4 | **工具开关** | 按类别分组勾选（Scapy / Pktgen / TRex），未勾选的工具不注册进图 | 全选 |
| 5 | **业务 PCAP 上传** | ≤ **50 MB**；创建时**按实验归档**到 `data/uploads/{run_id}/` | 可选 |

额外配置（保留现有能力，默认不暴露）：`max_iters`、`no_improve_limit`、运行模式（dry-run / pktgen-live / trex-live）、Pktgen/TRex 主机端口（默认 `topology.yaml`）。

> **安全红线**：`用户上限 = min(表单值, 硬上限常量)`，硬上限永远生效。

**AC**
1. Given 表单填写 5 项配置，When 点击「开始测试」，Then `POST /api/experiments` 返回 `{run_id, status}`，页面跳转详情页。
2. Given 目标 IP 不在 allowlist，When 提交，Then 后端 400 并返回具体错误，不创建实验。
3. Given 任一工具上限 > 硬上限，When 提交，Then 后端 400，返回 `{param, given, hard_limit}`。
4. Given 服务端未配置 `DEEPSEEK_API_KEY`，When 提交，Then 后端 400 提示"未配置 LLM API Key"（创建时预检，见 §12-E1）。
5. Given 上传 PCAP > 50 MB，When 上传，Then 拒绝并提示上限（`/api/upload/pcap` 校验）。
6. Given 已有实验在 running，When 创建新实验，Then 新实验 `status=queued`，前端提示"已加入排队"。

### FR-3 运行/详情页（点击「开始测试」后展示 4 项内容）

| 展示项 | 内容 | 数据来源 |
|--------|------|---------|
| **攻击类型** | 工具名 + 友好标签（完整映射见 §8.8） | `tool_call.name` + `args` |
| **攻击大小** | 归一化强度（pps / 真实 BPS/PPS / 时长 / 包长 / 流数 / 估算总包数），见 §8.5 | `args` + 工具结果 + Pktgen 统计 API |
| **推理过程** | 时序流：LLM 思考（**默认折叠为截断摘要，点击展开全文**）→ 文本 → 工具调用 → 工具结果 → HITL 决定 | `events`（落库） |
| **拨测指标** | **RTT 折线 + 成功率折线双轴图**，攻击窗口高亮区间（`markArea`）；面板同时显示 avg/min/max RTT、丢包率、成功率数字 | `probes` + `attacks.rtt` + `observation_window` |

**AC**
1. Given 实验 running，When 智能体产生思考/工具调用/结果，Then 详情页 ≤1s 内按 seq 顺序渲染对应事件。
2. Given 一条 reasoning 事件，Then 默认只显示 `summary`（截断摘要），点击后展开 `reasoning_content` 全文。
3. Given 一次流量工具调用完成，Then 出现一张攻击卡片：类型标签 + 大小数值 + 该窗口成功率 + HITL 状态。
4. Given 拨测数据到达，Then 双轴曲线实时追加，攻击窗口在时间轴上高亮。
5. Given 工具结果携带 `observation_window.covers_attack_window=false`，Then 对应攻击卡片显示警告标记与 note 原文。

### FR-4 历史详情回看

- 与运行详情页共用 UI；已结束实验为只读回放：按 `seq` 顺序重放全部事件、攻击卡片、拨测曲线与最终摘要。

**AC**
1. Given 一条 completed/stopped/error/interrupted 实验，When 打开详情页，Then 一次性加载完整事件并按序渲染。
2. Given 回放页，Then 不出现 HITL 按钮等交互控件。

### FR-5 HITL 审批（保留并增强）

- 详情页内弹窗，展示**将要实发的参数**（含 TRex 脚本预览与危险提示）；
- 批准 / 拒绝通过 WS 回传 `Command(resume=...)`；
- HITL 决定作为 `hitl` 事件落库（审计）。

**AC**
1. Given 智能体触发 `interrupt()`，When 收到 `hitl_request`，Then 弹窗展示参数（TRex 含脚本预览与危险提示）。
2. Given 操作员点击批准/拒绝，Then 后端收到并 resume，决定以 `hitl` 事件落库并回显给所有连接。
3. Given 实验详情页无操作员连接（断线），Then 实验保持挂起，直至重连后恢复审批（见 FR-6）。

### FR-6 断线重连（方案①：继续跑 + 补齐续读 + HITL 恢复）

**核心事实**：实验跑在**后端进程**，浏览器刷新/断网/关标签页，实验不停——服务端继续跑、继续发包、继续落库。

- 重连流程：前端重连 `/ws/{run_id}` 后，先 `GET /api/experiments/{id}?after_seq=本地最后seq` 补齐断线期间事件（"回放"），再订阅 WS 增量（"直播"）。
- WS 消息的 `seq` 与 `events.seq` **同源同值**（§8.3），重连对齐只认 `seq`。

**AC**
1. Given 详情页刷新/断网后重连，When 客户端带 `after_seq` 拉取，Then 补齐所有 `seq > after_seq` 的事件且无重复、无遗漏，随后 WS 增量续播。
2. Given 断线时服务端存在待决 HITL，When 重连，Then 重新弹出该 HITL 审批框（从 `events` 中最后一条未决 `hitl_request` 恢复）。
3. Given 断线期间实验已结束，When 重连，Then 补齐事件后显示结束状态与摘要。

### FR-7 实验排队

- 单实验并发模型 + FIFO 队列：`POST /api/experiments` 时若有实验在 running，新实验进 `queued`；前一个结束后自动启动队首。
- 取消排队 = 对 `queued` 实验执行软删除。

**AC**
1. Given 实验 A 在 running 且 B、C 已 queued，When A 结束，Then B 自动进入 running。
2. Given 某 queued 实验被取消，Then 其状态为软删除、不参与排队。
3. Given 队列中实验等待期间服务端重启，Then 启动时全部标记 interrupted（§12-E4）。

### FR-8 停止 / 取消 / 软删除

- running → 可停止（`POST /api/experiments/{id}/stop` → status=stopped）；
- queued → 可取消（软删除）；
- completed/stopped/error/interrupted → 可软删除：只置 `deleted_at`，**所有行（含子表）保留在库中**，查询默认过滤；不涉及物理/级联删除。

**AC**
1. Given 实验 running，When 请求停止，Then 状态变 stopped，`finished_at` 落时间戳，摘要计算并落库。
2. Given 实验 queued/running，When 请求删除，Then 后端 409 拒绝。
3. Given 实验已结束，When 软删除，Then 列表不可见；数据库中该行及子表数据仍存在且 `deleted_at` 非空。
4. Given 误删，When 手动将 `deleted_at` 置空（运维操作），Then 实验恢复可见。

---

## 7. 数据模型

### 7.1 存储引擎（已决策）

- **主存储：SQLite**（stdlib `sqlite3`，无新依赖）。文件路径：`data/attack_test.db`（加入 `.gitignore`）。
- **审计日志：JSONL**（保留现有 `log_tool` 产物，作为不可变审计留档，不参与查询）。
- **schema 迁移**：用 `PRAGMA user_version` 记录版本；v1 建表；后续变更用递增 `ALTER TABLE` 迁移脚本（`backend/storage.py` 内）。
- 不自动清理历史（已决策）；后续视文件大小再加归档开关。

### 7.2 表结构（SQLite v1）

```sql
-- 实验（一次攻防测试）
CREATE TABLE experiments (
  id            TEXT PRIMARY KEY,          -- run_id，如 'r_20261118_213000_ab12'
  created_at    TEXT NOT NULL,             -- ISO8601
  started_at    TEXT,
  finished_at   TEXT,
  status        TEXT NOT NULL,             -- queued|running|completed|stopped|error|interrupted
  stop_reason   TEXT,                      -- manual|error|completed（系统侧可判定的原因，见 §8.7）
  deleted_at    TEXT,                      -- 软删除标记（非 NULL 即已删除，查询时过滤）
  config        TEXT NOT NULL,             -- JSON：配置快照（见 §9.1 CreateExperimentRequest）
  summary       TEXT                       -- JSON：结束时一次性计算（见 §8.7）
);
CREATE INDEX idx_experiments_status ON experiments(status, created_at);

-- 事件流水（权威，实时与回放共用）
CREATE TABLE events (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  experiment_id TEXT NOT NULL REFERENCES experiments(id),
  seq           INTEGER NOT NULL,          -- 实验内自增序号（单一权威编号，WS 同源）
  ts            TEXT NOT NULL,             -- ISO8601
  kind          TEXT NOT NULL,             -- reasoning|ai_message|tool_call|tool_result|hitl|status|error
  payload       TEXT NOT NULL              -- JSON，按 kind 结构不同（见 §9.2）
);
CREATE UNIQUE INDEX idx_events_exp_seq ON events(experiment_id, seq);

-- 攻击事件（从 tool_result 派生的物化表，供"攻击类型/大小"卡片快速查询）
CREATE TABLE attacks (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  experiment_id TEXT NOT NULL REFERENCES experiments(id),
  seq           INTEGER NOT NULL,          -- 与派生它的 tool_result 事件 seq 一致
  ts            TEXT NOT NULL,
  attack_type   TEXT NOT NULL,             -- 归一化类型标识（见 §8.8）
  attack_label  TEXT NOT NULL,             -- 友好标签（中文）
  params        TEXT NOT NULL,             -- JSON：原始工具参数
  size          TEXT NOT NULL,             -- JSON：归一化强度，见 §8.5
  rtt           TEXT,                      -- JSON：rtt_during + attack_window + observation_window
  hitl          TEXT                       -- JSON：{requested, approved, params}
);
CREATE UNIQUE INDEX idx_attacks_exp_seq ON attacks(experiment_id, seq);

-- 拨测采样点（1 秒聚合，用于成功率时间序列图）
CREATE TABLE probes (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  experiment_id TEXT NOT NULL REFERENCES experiments(id),
  seq           INTEGER NOT NULL,          -- 与派生它的 probe 聚合序号一致
  ts            REAL NOT NULL,             -- time.time() epoch
  sent          INTEGER NOT NULL,
  received      INTEGER NOT NULL,
  avg_rtt_ms    REAL,                      -- 该秒平均 RTT（全丢时 NULL）
  loss_pct      REAL NOT NULL
);
CREATE INDEX idx_probes_exp_ts ON probes(experiment_id, ts);
```

**权威关系（已决策）**：`events` 是唯一权威流水；`attacks`/`probes` 是后端落库时**同步派生的物化表**（`attacks.seq` = 对应 `tool_result` 事件的 seq）。前端查询卡片/曲线走派生表，回放走 `events`；派生表可随时由 `events` 重建。

**软删除约定（已决策）**：删除实验只更新 `experiments.deleted_at`，所有行（含子表）保留在库中；所有查询默认过滤 `deleted_at IS NOT NULL` 的行。

### 7.3 存储量估算（`probes` 表）

- 按 **1 秒聚合** 存储（`sent/received/avg_rtt/loss_pct` 每秒一点）：10 分钟实验 = 600 行/实验，可接受。
- 聚合执行者与时机：`ExperimentManager` 在实验 running 期间启动 asyncio 后台任务，每秒取 `PingMonitor.get_stats(window_s=1)` 写 `probes` 并推 WS `probe` 消息；攻击窗口高亮由前端按 `attacks.rtt.attack_window` 时间戳对位。

### 7.4 摘要计算规则（`experiments.summary`）

实验**结束时一次性计算**（status 离开 running 时），字段：

```jsonc
{
  "best_rtt_ms": 12.3,          // attacks.rtt.rtt_during.avg_rtt_ms 的最大值；无攻击则 null
  "final_rtt_ms": 8.9,          // 最后一次攻击的 avg_rtt_ms；无攻击则 null
  "probe_success_rate": 96.2,   // probes 全量汇总 received/sent×100；无探针则 null
  "attack_count": 7,            // attacks 行数
  "steps": 42,                  // events 中 ai_message+tool_call 事件总数（衡量"步数"）
  "stop_reason": "completed",   // manual|error|completed（判定见下）
  "error": null,                // status=error 时的异常信息（截断 500 字）
  "final_text": "…"             // 最后一条 AI 文本 content（截断 2000 字）
}
```

**`stop_reason` 判定说明**：现有 `create_agent` ReAct 图**没有系统级迭代计数**（`max_iters`/`no_improve_limit` 只是提示词约束），所以系统侧只能可靠判定三种：`manual`（用户停止）、`error`（异常）、`completed`（智能体无更多工具调用、自然结束）。"达到 max_iters / 连续无改善"这两类原因**系统侧无法可靠识别**，一律记为 `completed`；若未来实现系统级轮数强制（Non-goals），再细分。

### 7.5 「攻击大小」归一化定义（`attacks.size`）

```jsonc
{
  "engine": "scapy" | "pktgen" | "trex",
  "rate": 100,                    // pps（scapy）；rate%（pktgen，仅 dry-run 时作为"配置值"展示）
  "duration_s": 10.0,             // 统一换算为秒
  "packet_size": 64,              // 字节
  "flow_count": 1,                // 流数（pktgen 无则为 0）
  "est_total_packets": 1000,      // 估算总包数 = rate × duration
  "est_mbps": 0.51,               // 估算吞吐
  "measured": {                   // 仅 Pktgen live 模式：真实测量值（来自统计 API）
    "pps_tx": 480000, "mbps_tx": 984.2,
    "pkts_tx_total": 4800000,     // 攻击前后 pktStats 差值
    "measured_at": 1730000000.0
  }
}
```

- **Scapy**：`rate=pps`，`est_total_packets = pps × duration_s`，`est_mbps ≈ pps × packet_size × 8 / 1e6`。
- **Pktgen live**：优先用 **Pktgen 统计 API 拿真实 BPS/PPS**（§7.6）；dry-run 无真实流量，只填配置字段（`rate%`、`duration_s`、`packet_size`），`measured=null`。
- **TRex**：`size` 降级为 `{engine:"trex", script:filename, elapsed_s}`（无法从结果反推包数）。

### 7.6 Pktgen 统计 API（真实 BPS/PPS 来源）

Pktgen 自带统计 API，**无需用 `rate% × 线速` 估算**。现有 `stats_monitoring` skill（`dsl/skills/stats_monitoring.yaml`）已在轮询这些接口：

| Pktgen Lua API | 含义 | 攻击大小的用途 |
|----------------|------|----------------|
| `pktgen.portStats(port, "rate")` | 速率统计表：每秒包数（PPS）+ 每秒兆比特（Mbps/Mbits） | **攻击大小的真实 PPS / BPS** |
| `pktgen.pktStats(port)` | 累计收发包计数 | 本次攻击实际发包总数（前后差值） |
| `pktgen.isSending(port)` | 是否正在发包 | 判断攻击是否在窗口内 |
| `pktgen.portSizes(port)` | 端口包长统计 | 包长分布 |

**当前实现的问题**：`stats_monitoring` 只用 `prints()` 把结果打印成**文本**，`execute_skill_live()` 返回的 `response` 是原始字符串，未解析成数字。要把它用作"攻击大小"，需要改造：
1. 让 Lua 把 `pktgen.portStats(port, "rate")` 的表**结构化输出**（`key=value` 或 JSON），Python 端解析出 `pps_tx` / `mbps_tx`；
2. 攻击窗口采样：**攻击前清零统计 → 攻击 → 攻击后读取速率统计**，得到本次攻击的峰值/平均 BPS/PPS；
3. dry-run 模式无真实流量 → 攻击大小退化为"配置参数"（`rate%`、`duration`、`pktSize`）。

> 备注：`portStats(..., "rate")` 返回表的字段名随 Pktgen 版本略有差异（`pkts_tx`/`mbits_tx` 或 `pkts_per_sec`/`mbits_per_sec` 等），接入时需对实际 Pktgen 版本实测确认字段名。

### 7.7 「拨测成功率」定义

```
probe_success_rate = received / sent × 100%   (sent > 0)
loss_pct           = (1 − received / sent) × 100%
```

- **整场实验成功率**：`probes` 表全量汇总。
- **单次攻击窗口成功率**：`attacks.rtt.rtt_during.loss_pct`（已存在）。
- 与现有代码对齐：`PingMonitor.get_stats()` 已返回 `sent_count/received/loss_pct`；`build_rtt_observation()` 已返回 `loss_pct/total_sent/total_received`。前端把 `loss_pct` 换为 `1 − loss_pct` 展示，**不改底层采集**。
- **100% 丢包时（已决策）**：不强行定性。原样展示"丢包率 100% / 成功率 0%"，并把 `observation_window.note`（"所有探测均丢失，目标可能不可达**或**攻击完全阻断了 ICMP"）原文展示，由观看者自行判断。

### 7.8 攻击类型映射表（19 工具 → 归一化）

| 工具 | 是否攻击事件 | `attack_type` | `attack_label` | 备注 |
|------|:---:|------|------|------|
| `traffic_send` | ✅ | `scapy_udp` | Scapy UDP 流量 | |
| `mixed_traffic_send` | ✅ | `scapy_mixed` | Scapy 混合流量 | 标签附 stream 数 |
| `pktgen_udp_flood` | ✅ | `pktgen_udp_flood` | Pktgen UDP 泛洪 | |
| `pktgen_tcp_flood` | ✅ | `pktgen_tcp_flood` | Pktgen TCP 泛洪 | 标签附 `tcp_flags`（如 SYN） |
| `pktgen_icmp_flood` | ✅ | `pktgen_icmp_flood` | Pktgen ICMP 泛洪 | |
| `pktgen_arp_flood` | ✅ | `pktgen_arp_flood` | Pktgen ARP 泛洪 | |
| `pktgen_range_scan` | ✅ | `pktgen_range_scan` | Pktgen 参数扫描 | 标签附 `scan_field` |
| `pktgen_packet_sequence` | ✅ | `pktgen_packet_sequence` | Pktgen 序列包 | |
| `pktgen_pcap_replay` | ✅ | `pktgen_pcap_replay` | Pktgen PCAP 重放 | |
| `run_python_file` | ✅（仅 live） | `trex_script` | TRex 脚本执行 | dry-run 不算攻击 |
| `ping_rtt` | ❌ | — | — | 拨测类，记入 `tool_result` 事件即可 |
| `pcap_profile` | ❌ | — | — | 分析类 |
| `start/read/stop_ping_monitor` | ❌ | — | — | 监控控制类 |
| `log_result` | ❌ | — | — | 日志类 |
| `pktgen_stats_monitor` / `pktgen_stop_and_reset` | ❌ | — | — | 观测/控制类 |
| `write_python_file` | ❌ | — | — | 准备类 |

> 抽取规则：**只有"产生流量"的工具调用**（上表 ✅）在 `tool_result` 落库时同步派生 `attacks` 行；其余工具只进 `events`。

---

## 8. API 契约

### 8.1 REST API

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/experiments?status=&cursor=&limit=` | 列表（`status` 为六态之一，可选；`cursor` 为分页游标=上一页最后一条 `created_at,id`；默认 limit=20） |
| `POST` | `/api/experiments` | 创建实验（请求体见下），返回 `{run_id, status}` |
| `GET` | `/api/experiments/{id}` | 详情：`{experiment, attacks, probes}`；支持 `?after_seq=N` 增量返回 `events`（`seq>N`）——断线重连用 |
| `GET` | `/api/experiments/{id}/events?after_seq=N&limit=` | 增量拉取事件流（重连补齐专用） |
| `POST` | `/api/experiments/{id}/stop` | 停止运行中的实验 |
| `DELETE` | `/api/experiments/{id}` | **软删除**：置 `deleted_at`；`queued/running` 返回 409 |
| `GET` | `/api/meta/options` | 表单元数据：allowlist `hosts[]`、工具清单（含分类/默认值与硬上限）、运行模式选项 |
| `POST` | `/api/upload/pcap` | 上传（≤50MB），返回 `{file_path, file_name, size_bytes}`；创建实验时归档到 `data/uploads/{run_id}/` |

#### 8.1.1 `POST /api/experiments` 请求体（契约）

```jsonc
{
  "target_ip": "100.1.11.20",              // 必填，∈ allowlist
  "user_prompt": "重点探索 UDP 洪水对 RTT 的影响",  // 选填，注入提示词
  "tool_limits": {                          // 选填；缺省用 experiment.json 软上限；每项 ≤ 硬上限
    "pps": 500, "duration_s": 10, "packet_size": 256,
    "flow_count": 4, "iat_jitter_ms": 10,
    "pktgen_rate": 80, "pktgen_duration_ms": 10000
  },
  "enabled_tools": ["traffic_send", "mixed_traffic_send", "ping_rtt",   // 选填；缺省=全选
                     "start_ping_monitor", "read_ping_stats", "stop_ping_monitor",
                     "pcap_profile", "log_result",
                     "pktgen_udp_flood", "pktgen_tcp_flood", "pktgen_icmp_flood",
                     "pktgen_arp_flood", "pktgen_range_scan", "pktgen_packet_sequence",
                     "pktgen_pcap_replay", "pktgen_stats_monitor", "pktgen_stop_and_reset",
                     "write_python_file", "run_python_file"],
  "pcap_path": "data/uploads/inbox/ab12_xxx.pcap",   // 选填，上传接口返回的路径
  "max_iters": 20,                          // 选填
  "no_improve_limit": 5,                    // 选填
  "mode": "dry_run" | "pktgen_live" | "trex_live"    // 选填，默认 dry_run
}
```

校验顺序（全部通过才落库）：`target_ip ∈ allowlist` → `enabled_tools` 名称合法且至少含 1 个观测类工具 → `tool_limits` 各项 ≤ 硬上限 → `DEEPSEEK_API_KEY` 已配置 → PCAP 文件存在且 ≤50MB。任一失败返回 400 `{error, detail}`。

#### 8.1.2 列表响应示例

```jsonc
{
  "items": [{
    "id": "r_20261118_213000_ab12",
    "target_ip": "100.1.11.20",
    "status": "completed",        // queued|running|completed|stopped|error|interrupted
    "created_at": "2026-11-18T21:30:00+08:00",
    "summary": { "best_rtt_ms": 12.3, "probe_success_rate": 96.2,
                 "attack_count": 7, "stop_reason": "completed" }
  }],
  "total": 42,
  "next_cursor": "2026-11-17T10:00:00+08:00,r_20261117_100000_zz99"
}
```

### 8.2 WebSocket 协议（`/ws/{run_id}`）

- `seq` 与 `events.seq` **同源同值**；重连对齐只认 `seq`。
- 连接角色（§12-E9）：**第一个连接该 run 的 WS 为"操作员"**，可发 `hitl_response`/`stop_experiment`；后续连接为"旁观"（只收流，发送控制消息时收到 `error`）。

| type | 载荷 | 说明 / 示例 |
|------|------|------|
| `status` | `{status, run_id}` | `{"status":"starting","run_id":"r_..."}` |
| `reasoning` | `{seq, ts, content, reasoning_content, summary}` | `summary` 为折叠摘要（§10.4），`reasoning_content` 为全文 |
| `ai_message` | `{seq, ts, content}` | 无 tool_calls 的纯文本输出 |
| `tool_call` | `{seq, ts, name, args}` | `{"name":"traffic_send","args":{"dst_ip":"...","pps":500}}` |
| `tool_result` | `{seq, ts, name, result}` | 工具结果原文（可截断，全量在 DB） |
| `attack` | `{seq, ts, attack_type, attack_label, params, size, rtt}` | 与 `attacks` 表同源（供卡片渲染） |
| `probe` | `{seq, ts, sent, received, avg_rtt_ms, loss_pct, success_rate}` | 每秒聚合点（供曲线） |
| `hitl_request` | `{seq, ts, message, params}` | TRex 含 `code_preview` 与 `warning` |
| `hitl_response` | `{seq, ts, approved}` | 决定回显（含旁观连接） |
| `experiment_done` | `{status, summary}` | 结束（含 §7.4 摘要） |
| `storage_error` | `{message}` | 落库失败降级告警（§12-E8），实验继续 |
| `error` | `{code, message}` | `code ∈ {unknown_msg, not_operator, invalid_json, ...}` |

前端上行消息：`{type:"hitl_response", data:{approved:bool}}`、`{type:"stop_experiment"}`（仅操作员连接）。

---

## 9. 前端页面与交互

- **技术栈**：纯 HTML/JS/CSS（无构建）。
- **图表（已决策）**：**ECharts 本地 vendor**——把 `echarts.min.js` 下载到 `frontend/vendor/`，页面本地引用，不依赖外网；如需 CDN 可一行切换。用**双 Y 轴折线**：左轴 RTT(ms)、右轴成功率(%)；攻击窗口用 `markArea` 高亮。
- **列表页**：卡片/表格 + 六态徽章 + 摘要指标 + 「新建实验」；5s 轮询刷新。
- **新建页**：5 项配置分组表单；工具开关按「Scapy / Pktgen / TRex」分组勾选；上限输入带硬上限提示与前端即时校验；PCAP 上传带 50MB 提示。
- **详情页（实时 + 回看）**：三栏或分 Tab：
  1. **攻击时间线**：每次攻击一张卡片（类型标签 + 大小数值/测量值 + 窗口成功率 + HITL 状态 + 对齐警告）；
  2. **推理流**：`reasoning` 默认折叠摘要、点击展开全文；`tool_call`/`tool_result` 可展开；
  3. **拨测图表**：RTT + 成功率双轴 + 攻击窗口高亮。
- **HITL 弹窗**：嵌入详情页，展示参数 + 脚本预览 + 批准/拒绝。
- **截断摘要规则（§10.4）**：`summary = 去换行归一化后的 reasoning_content 前 80 个 Unicode 字符 + "…"`；`reasoning_content` 为空时用 `content` 前 80 字。

---

## 10. 思考链折叠摘要（决策落地）

- `reasoning_content` **全量入库**（`events.payload`），前端默认折叠。
- 折叠摘要 = **截断摘要**（前 80 字符，规则见 §9），不做 LLM 总结（v1）。
- AI 正文 `content` 正常展示不折叠。

---

## 11. 决策记录（全部已拍板）

| # | 事项 | 决策 |
|---|------|------|
| 1 | 并发模型 | 方案 A：同一时刻只跑一个实验 + FIFO 排队；历史存多条 |
| 2 | 思考过程 | 全量入库 + 前端默认折叠 + 截断摘要（80 字） |
| 3 | 攻击大小量化 | Pktgen 用统计 API 拿真实 BPS/PPS；dry-run 退化配置参数；TRex 降级脚本名+耗时 |
| 4 | 上限语义 | 每实验软上限（≤ 全局硬上限，硬上限不可下放） |
| 5 | 鉴权 | 暂不做 |
| 6 | 断线重连 | 方案①：继续跑 + 补齐续读 + HITL 恢复 |
| 7 | PCAP 归属 | 按实验归档到 `data/uploads/{run_id}/` |
| 8 | 历史保留 | 暂不自动清理，全量保留 |
| 9 | 成功率与 RTT | 两者都在前端展示（双轴图） |
| 10 | 删除语义 | 软删除（置 `deleted_at`，不物理删除、不级联） |
| 11 | 存储引擎 | SQLite（stdlib）+ JSONL 审计日志 |
| 12 | 图表方案 | ECharts 本地 vendor（无外网依赖） |
| 13 | PCAP 上限 | 50 MB |
| 14 | 100% 丢包语义 | 原样展示，附 note 原文，不强行定性 |
| 15 | 重启恢复 | running/queued 一律标记 interrupted，不自动恢复 |
| 16 | events/attacks/probes 关系 | events 权威流水；attacks/probes 为派生物化表 |

---

## 12. 边界与失败场景（处理约定）

| # | 场景 | 约定 |
|---|------|------|
| E1 | 无 API key / LLM 请求失败 | 创建时**预检** API key（缺失 → 400）；运行中 LLM 异常 → 实验 status=error，推 `error` 事件，`summary.error` 记录（截断 500 字） |
| E2 | 目标 100% 丢包 | 原样展示 + note 原文（决策 #14） |
| E3 | Pktgen/TRex 连接失败 | 工具返回失败结果照常落库；攻击卡片显示失败态（标签灰 + error 信息） |
| E4 | 服务端进程重启 | 启动时批量把 `running/queued` → `interrupted`（`finished_at=now`）；不自动恢复（决策 #15） |
| E5 | 运行中/排队中删除 | 后端 409 拒绝，前端禁用删除按钮 |
| E6 | 取消排队 | queued 实验软删除即取消；队列不持久化（重启按 E4 处理） |
| E7 | PCAP 超限 | ≤50MB，超限 `/api/upload/pcap` 400（决策 #13） |
| E8 | 落库失败（磁盘满等） | **不中断实验**：记 error 日志 + 推 `storage_error` 告警，实时流照常；结束时 `summary` 附 `storage_warning: true` |
| E9 | 多标签页打开同一实验 | 第一个 WS 连接为操作员，其余旁观（发控制消息收 `error: not_operator`） |
| E10 | probes 聚合 | `ExperimentManager` 运行期 asyncio 后台任务每秒聚合（§7.3） |

---

## 13. 关键代码改造点（映射到现有文件）

| 现有文件 | 改造 |
|----------|------|
| `backend/storage.py`（新增） | SQLite 持久化层：建表（`PRAGMA user_version` 迁移）、CRUD、事件追加（seq 分配）、派生抽取（attacks/probes）、摘要计算、软删除、启动时孤儿状态清理（E4） |
| `backend/experiment.py` | ① `create(config)` 返回 `run_id` + 排队逻辑；② 事件落库回调 + WS 推送；③ `_msg_to_dict` 补 `reasoning_content`；④ 工具结果 → attack 抽取 + probes 每秒聚合任务；⑤ 结束时算摘要；⑥ **工具执行放入 executor**（修复同步阻塞事件循环）；⑦ 操作员/旁观连接管理 |
| `backend/server.py` | 新增 REST `/api/experiments*`、`/api/meta/options`；WS 路由 `/ws/{run_id}`；协议扩展；PCAP 50MB 校验 |
| `src/agent/graph.py` | `build_graph()` 增加 `tools`（子集）与 `tool_limits` 参数 |
| `src/agent/tools.py` | 工具上限改为"硬上限常量 + 每实验软上限"（`contextvar` 或单实验 env） |
| `src/main.py` | 抽出可复用 `apply_run_config()`，CLI 与 Web 共用 |
| `dsl/skills/stats_monitoring.yaml` | `pktgen.portStats(port,"rate")` 结构化输出，供后端解析真实 PPS/BPS |
| `frontend/` | 重构三视图 + 攻击卡片/推理流/双轴图 + HITL 弹窗；`frontend/vendor/echarts.min.js` |
| `src/config/experiment.json` | 增加 `tool_limits` 默认软上限与工具开关默认值 |
| `data/` | 新增 `attack_test.db`、`uploads/{run_id}/`（`.gitignore`） |

---

## 14. 分阶段实施建议

| 阶段 | 内容 | 产出 |
|------|------|------|
| **P0 数据层** | SQLite 持久化 + 事件落库 + 派生表 + 摘要计算 + 状态机/迁移 | `backend/storage.py` + 单测 |
| **P1 后端 API** | 列表/创建/详情(增量)/停止/软删除 + `meta/options` + 创建校验（含 API key 预检、50MB） | REST + 单测 |
| **P2 实时事件** | WS 协议扩展 + attack 抽取 + probes 聚合 + executor 化工具执行 + 排队启动 | `experiment.py` 改造 + 集成测试 |
| **P3 前端重构** | 三视图 + 新建表单 + 详情页（卡片/推理流/双轴图）+ HITL 弹窗 + ECharts vendor | `frontend/` 重写 |
| **P4 历史回看** | 回放 + 列表过滤/分页/软删除 | 前端 + API 打磨 |
| **P5 加固** | 断线重连（补齐续读 + HITL 恢复）、排队队列、PCAP 归档、重启清理、多标签角色 | 收尾 + 端到端验证 |

---

## 15. 验收标准（草案，对应 FR 编号）

- [ ] FR-1：列表分页/过滤/软删除隐藏/5s 状态刷新正常；
- [ ] FR-2：5 项配置齐全；非法 IP / 超限上限 / 无 API key / >50MB PCAP 均被后端拒绝并有明确报错；运行中创建进入排队；
- [ ] FR-3：实时看到攻击类型、攻击大小（Pktgen live 含真实 BPS/PPS）、推理过程（折叠摘要可展开）、RTT+成功率双轴曲线；
- [ ] FR-4：历史实验可完整回放、只读；
- [ ] FR-5：HITL 在详情页审批，决定落库审计；
- [ ] FR-6：刷新/断线重连后事件补齐无重复无遗漏，挂起的 HITL 可恢复审批；
- [ ] FR-7：前一个实验结束后队首自动启动；
- [ ] FR-8：停止/取消/软删除语义正确；软删除后数据仍在库中；
- [ ] 安全回归：所有流量工具仍受硬上限 + allowlist 约束（软上限只可下修）；
- [ ] 服务端重启后 running/queued 标记 interrupted，历史仍可查看回放。

---

*Spec v0.2 · 16 项决策已全部拍板 · 本文档为实施阶段的唯一事实源（single source of truth）。*
