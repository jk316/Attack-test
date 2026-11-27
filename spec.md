# 攻防智能体 Web 控制台 — 需求与设计规格（Spec）

> 状态：**v0.3（按当前 React 前端对齐重写，作为后端改造的事实源）**
> 目标分支：`jk316/merge-bugfix-webui`
> 定位：把「单次、单屏」Web 控制台，升级为「**实验为中心**」的攻防演练控制台——
> 可配置创建、可实时观测（ICMP / HTTP / 清洗前后流量）、可总结回看、可沉淀经验教训。

---

## 1. 背景与目标

当前控制台是「最小可用雏形」。本规格目标是把实验作为一等公民实体，围绕
「实验列表 → 新建实验 → 运行详情（实时观测）→ 总结回看」这条主线组织前端，
后端统一持久化「实验配置、运行状态、推理流、攻击事件、ICMP/HTTP 拨测指标、
清洗前后流量、经验教训」。

核心新增能力（相对旧版）：
1. **双拨测观测**：ICMP 拨测（RTT + 丢包率）与 HTTP 拨测（成功率 + 首字节 TTFB）分开建模与展示。
2. **清洗前后流量观测**：对接外部清洗设备，实时观测「清洗前流量（攻击+业务）」与「清洗后流量（放行业务）」。
3. **实验总结页**：实验结束后产出「最终指标 + 实验基本信息 + 攻击过程说明 + 经验教训总结」。
4. **经验教训沉淀**：明确「打什么攻击最有效」，指导下一次实验。

---

## 2. 术语表

| 术语 | 含义 |
|------|------|
| **实验（Experiment / Run）** | 一次从创建到结束的攻防测试。有唯一 `run_id`、配置、状态、结果摘要。 |
| **攻击（Attack）** | 实验中一次「产生流量」的工具调用（`traffic_send`、`pktgen_udp_flood`、`run_python_file` 实发等）。 |
| **攻击类型（Attack Type）** | 工具/协议类型（UDP Flood、TCP SYN Flood、混合流量、Pktgen 线速泛洪、TRex 脚本等），见 §8.8。 |
| **攻击大小（Attack Size / Intensity）** | 归一化攻击强度（pps / 真实 BPS/PPS / 时长 / 包长 / 流数 / 估算总包数）。 |
| **推理过程（Reasoning Trace）** | 智能体每步：LLM 思考（`reasoning_content`）→ 文本 → 工具调用 → 工具结果 → HITL 审批 的完整时序。 |
| **ICMP 拨测（Probe）** | 后台 `PingMonitor` 对目标的持续 ICMP 探测（`fping -Q` 或系统 `ping`），产出 RTT 与丢包率。 |
| **丢包率（Loss Rate）** | `1 − received/sent × 100%`，即 `100% − 成功率`。 |
| **HTTP 拨测（HTTP Probe）** | 后台 `HttpMonitor` 对业务 HTTP 端点的持续 `curl` 探测，产出成功率、TTFB、5xx 率。 |
| **TTFB（Time To First Byte）** | HTTP 首字节响应时间，反映业务延迟退化。 |
| **清洗前流量（Pre-clean Traffic）** | 进入清洗设备前的总流量（攻击流量 + 业务流量）。 |
| **清洗后流量（Post-clean Traffic）** | 清洗设备放行的业务流量（攻击流量被过滤后）。 |
| **清洗设备（Cleaner）** | 外部流量清洗/观测服务，通过 `src_cidr` 区分业务与攻击流量。 |
| **经验教训（Lesson）** | 实验结束后沉淀的结论：哪种攻击手段对当前目标最有效，用于指导下一次实验。 |
| **HITL** | Human-in-the-loop 人工审批门控，所有流量工具实发前暂停等待操作员批准。 |

---

## 3. 总体设计

### 3.1 前端信息架构（四条主线）

```
控制台
├── ① 实验列表页（默认首页 /）
│      └── 历史实验表格 + 「新建实验」按钮
├── ② 新建实验（CreateExperimentModal 弹窗）
│      └── 5 项配置 → 点击「开始测试」
├── ③ 实验运行/详情页（/experiments/:id）
│      ├── 左栏 3 个图：清洗前后流量 / RTT+丢包率 / HTTP 成功率+TTFB
│      └── 右栏：攻击时间线 + 智能体推理流
├── ④ 实验总结页（/experiments/:id/summary）
│      ├── 最终指标 KPI
│      ├── 实验基本信息
│      ├── 攻击过程说明
│      └── 经验教训总结
└── ⑤ HITL 审批（弹窗，嵌入详情页）
```

> 侧边导航可折叠（只留图标）。技术栈为 **React + Vite + ECharts**（npm 依赖，非本地 vendor）。

### 3.2 后端数据流

```
新建实验表单
   │  POST /api/experiments（校验 allowlist / 上限 / API key / PCAP）
   ▼
ExperimentManager.create(config)
   │  1) 持久化 experiment(status=queued|running)
   │  2) 若配置了攻击网段 → 调清洗设备 POST /experiments/start 启动观测（得 task_id）
   │  3) 启动后台采集任务：
   │       ├─ ICMP 拨测（PingMonitor）→ 1s 聚合写 probes
   │       ├─ HTTP 拨测（HttpMonitor）→ 1s 聚合写 http_probes
   │       └─ 清洗流量（轮询清洗设备）→ 1s 采样写 clean_flows
   │  4) WS /ws/{run_id} 推送事件流（seq 自增）
   ▼
graph.ainvoke() ──► 事件流（reasoning / ai_message / tool_call / tool_result / hitl / status / error）
                          │
                          ├──► 实时推给前端（WS）
                          └──► 追加写 events 表
                                  └─► 同步派生：attacks（流量工具）/ probes / http_probes / clean_flows
实验结束 ──► 一次性计算 summary ──► 生成 lessons（经验教训）──► status=completed/stopped/error
```

> 权威关系：`events` 是权威流水；`attacks`/`probes`/`http_probes`/`clean_flows` 是派生物化表，
> 只为查询快，永远可由 `events` + 采集数据重建。

### 3.3 实验状态机

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

删除约束：`queued`/`running` 不允许删除；`completed`/`stopped`/`error`/`interrupted` 可软删除。

---

## 4. 功能需求（FR + 验收标准 AC）

### FR-1 实验历史列表

- 展示所有未软删除的实验，每行含：实验 ID（短 id）、目标 IP、状态徽章、创建时间、结果摘要。
- 状态徽章：`运行中 / 排队中 / 已完成 / 已停止 / 失败 / 中断`。
- 支持状态过滤、时间倒序（默认）、分页；列表页 5s 轮询 `GET /api/experiments` 刷新。

### FR-2 创建新实验（表单，5 项配置）

| # | 配置项 | 说明 | 默认值来源 |
|---|--------|------|-----------|
| 1 | 攻击 IP | 下拉框给出 `allowlist.json` 的 `hosts[]`，手动输入后端强校验 | `allowlist.json` |
| 2 | 用户提示词 | 自由文本，注入 user message 与 system prompt | 空 |
| 3 | 攻击工具上限 | 每实验软上限（≤ 硬上限）：pps、duration_s、packet_size、flow_count、pktgen rate 等 | `experiment.json` |
| 4 | 工具开关 | 按类别勾选（Scapy / Pktgen / TRex），未勾选不注册进图 | 全选 |
| 5 | 业务 PCAP 上传 | ≤ 50 MB；按实验归档到 `data/uploads/{run_id}/` | 可选 |

> 额外（保留现有能力，默认不暴露）：`max_iters`、`no_improve_limit`、运行模式、
> **清洗观测网段**（`attack_cidr` / `business_cidr`，见 §6）。

### FR-3 运行/详情页（实时观测）

左栏 3 个图 + 右栏 2 个卡片：

| 位置 | 内容 | 数据来源 |
|------|------|---------|
| 左-图1 | **攻击流量 · 清洗前/后**（双 Y 轴 Mbps，攻击窗口高亮） | `clean_flows` |
| 左-图2 | **RTT 拨测 · RTT / 丢包率**（双 Y 轴） | `probes` |
| 左-图3 | **HTTP 拨测 · 成功率 / TTFB**（双 Y 轴） | `http_probes` |
| 右-卡1 | **攻击时间线**（每张卡片：类型 + 大小 + 窗口成功率 + HITL 状态） | `attacks` |
| 右-卡2 | **智能体推理流**（reasoning 默认折叠摘要、可展开全文） | `events` |

- 右栏两卡片**内部滚动、按 2:3 分高度**，页面不因内容增多而变长。

**AC**
1. Given 实验 running，When 有拨测/清洗数据，Then 3 个图实时追加、攻击窗口高亮。
2. Given 一次流量工具调用完成，Then 出现攻击卡片（类型 + 大小 + 窗口成功率 + HITL 状态）。
3. Given `covers_attack_window=false`，Then 对应攻击卡片显示警告标记与 note 原文。
4. Given reasoning 事件，Then 默认显示截断摘要，点击展开全文。

### FR-4 实验总结页（新增）

路由 `/experiments/:id/summary`，四块内容：

1. **最终指标 KPI**：最终 RTT、最终丢包率、ICMP 拨测成功率、HTTP 成功率、攻击次数。
2. **实验基本信息**：新建实验时填写的全部配置（目标 IP、提示词、参数上限、工具开关、PCAP、迭代预算、模式）。
3. **攻击过程说明**：按时间叙述每轮攻击（手段 + 参数 + 效果），由 `attacks` 派生。
4. **经验教训总结**：明确「打什么攻击最有效」，指导下次实验（见 §10）。

**AC**
1. Given 实验结束，When 打开总结页，Then 四块内容齐全、可读。
2. Given 回看历史实验，Then 总结页只读（无交互控件）。
3. Given 详情页，When 点击「实验总结」按钮，Then 跳转总结页。

### FR-5 HITL 审批（保留）

- 详情页内弹窗展示将实发的参数（TRex 含脚本预览与危险提示）；批准/拒绝经 WS 回传；
  HITL 决定作为 `hitl` 事件落库。

### FR-6 断线重连（保留）

- 实验跑在后端进程，浏览器刷新/断线实验不停；重连后 `GET /api/experiments/{id}?after_seq=N` 补齐事件，再订阅 WS 增量。
- WS 的 `seq` 与 `events.seq` 同源同值。

### FR-7 实验排队（保留）

- 单实验并发 + FIFO 队列；`POST /api/experiments` 时若有实验在 running，新实验进 `queued`，前一个结束后自动启动。

### FR-8 停止 / 取消 / 软删除（保留）

- running 可停止；queued 可取消（软删除）；已结束可软删除（置 `deleted_at`，行保留）。

---

## 5. 数据模型（SQLite v1）

主存储 **SQLite**（stdlib `sqlite3`）。文件 `data/attack_test.db`（`.gitignore`）。
迁移用 `PRAGMA user_version`，v1 建表，后续 `ALTER TABLE` 递增。

```sql
-- 实验
CREATE TABLE experiments (
  id            TEXT PRIMARY KEY,          -- run_id
  created_at    TEXT NOT NULL,
  started_at    TEXT,
  finished_at   TEXT,
  status        TEXT NOT NULL,             -- queued|running|completed|stopped|error|interrupted
  stop_reason   TEXT,                      -- manual|error|completed
  deleted_at    TEXT,                      -- 软删除标记
  config        TEXT NOT NULL,             -- JSON 配置快照（含清洗观测网段）
  summary       TEXT                       -- JSON 结束时一次性计算（§7.4）
);
CREATE INDEX idx_experiments_status ON experiments(status, created_at);

-- 事件流水（权威）
CREATE TABLE events (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  experiment_id TEXT NOT NULL REFERENCES experiments(id),
  seq           INTEGER NOT NULL,
  ts            TEXT NOT NULL,
  kind          TEXT NOT NULL,             -- reasoning|ai_message|tool_call|tool_result|hitl|status|error
  payload       TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_events_exp_seq ON events(experiment_id, seq);

-- 攻击事件（从 tool_result 派生）
CREATE TABLE attacks (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  experiment_id TEXT NOT NULL REFERENCES experiments(id),
  seq           INTEGER NOT NULL,
  ts            TEXT NOT NULL,
  attack_type   TEXT NOT NULL,
  attack_label  TEXT NOT NULL,
  params        TEXT NOT NULL,
  size          TEXT NOT NULL,
  rtt           TEXT,                      -- rtt_during + observation_window
  hitl          TEXT                       -- {requested, approved, params}
);
CREATE UNIQUE INDEX idx_attacks_exp_seq ON attacks(experiment_id, seq);

-- ICMP 拨测采样（1s 聚合）
CREATE TABLE probes (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  experiment_id TEXT NOT NULL REFERENCES experiments(id),
  ts            REAL NOT NULL,
  sent          INTEGER NOT NULL,
  received      INTEGER NOT NULL,
  avg_rtt_ms    REAL,
  loss_pct      REAL NOT NULL
);
CREATE INDEX idx_probes_exp_ts ON probes(experiment_id, ts);

-- HTTP 拨测采样（1s 聚合）
CREATE TABLE http_probes (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  experiment_id TEXT NOT NULL REFERENCES experiments(id),
  ts            REAL NOT NULL,
  total         INTEGER NOT NULL,
  success_count INTEGER NOT NULL,
  success_rate  REAL NOT NULL,
  avg_ttfb_ms   REAL,
  five_xx_rate  REAL NOT NULL,
  timeout_count INTEGER NOT NULL,
  status_codes  TEXT                       -- JSON {code: count}
);
CREATE INDEX idx_http_probes_exp_ts ON http_probes(experiment_id, ts);

-- 清洗前后流量采样（1s）
CREATE TABLE clean_flows (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  experiment_id TEXT NOT NULL REFERENCES experiments(id),
  task_id       TEXT,                      -- 清洗设备观测任务 id
  ts            REAL NOT NULL,
  clean_before_mbps REAL NOT NULL,         -- 清洗前总流量
  clean_after_mbps  REAL NOT NULL          -- 清洗后放行业务流量
);
CREATE INDEX idx_clean_flows_exp_ts ON clean_flows(experiment_id, ts);

-- 经验教训（实验结束生成）
CREATE TABLE lessons (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  experiment_id TEXT NOT NULL REFERENCES experiments(id),
  title         TEXT NOT NULL,             -- 如「最有效手段：UDP 泛洪」
  text          TEXT NOT NULL,             -- 结论正文
  attack_type   TEXT,                      -- 关联的最有效攻击类型
  effectiveness TEXT                       -- 排序/强弱标记
);
CREATE INDEX idx_lessons_exp ON lessons(experiment_id);
```

### 5.1 摘要计算规则（`experiments.summary`）

实验结束时一次性计算：

```jsonc
{
  "final_rtt_ms": 189.4,          // 最后一次攻击的 avg_rtt_ms；无攻击 null
  "final_loss_pct": 74.0,         // 最后一次攻击窗口的丢包率
  "probe_success_rate": 12.0,     // ICMP probes 全量 received/sent×100
  "http_success_rate": 28.0,      // http_probes 全量 success_rate 均值
  "http_ttfb_ms": 1200.0,         // http_probes 全量 avg_ttfb 峰值/末值
  "attack_count": 3,
  "steps": 42,
  "stop_reason": "completed",
  "error": null,
  "final_text": "…"
}
```

### 5.2 「攻击大小」归一化（`attacks.size`）

**目的**：把异构攻击参数（Scapy 的 `pps`、Pktgen 的 `rate%`、TRex 的脚本）统一成
一个「相对强度」结构，供前端攻击卡片展示「这次攻击多大」。**它是强度参考值，不是精确测带宽。**

```jsonc
{
  "engine": "scapy" | "pktgen" | "trex",
  "rate": 100,                    // pps（scapy）；rate%（pktgen 配置值）
  "duration_s": 10.0,
  "packet_size": 64,
  "flow_count": 1,
  "est_total_packets": 1000,      // 估算总包数 = rate × duration
  "est_mbps": 0.51,               // 估算吞吐
  "measured": {                   // 仅 live 模式有；dry-run 为 null
    "pps_tx": 480000,
    "mbps_tx": 984.2,
    "pkts_tx_total": 4800000
  }
}
```

三档边界（明确「估算 vs 实测 vs 降级」）：

| 引擎/模式 | 怎么填 `size` | 性质 |
|-----------|--------------|------|
| **Scapy**（软件发包） | `rate=pps`；`est_total_packets = pps × duration_s`；`est_mbps ≈ pps × packet_size × 8 / 1e6` | **确定性计算**，较准（发包由代码按 pps 控制） |
| **Pktgen dry-run**（未实发） | 只填 `rate%`、`duration_s`、`packet_size`；`measured = null` | **配置值**——是「计划发多少」，不是「实际发多少」 |
| **Pktgen live**（实发） | 优先用 Pktgen 统计 API 拿 `measured`（真实 PPS/BPS，`pktgen.portStats(port,"rate")`）；`est_*` 仍保留作参考 | **实测值**——来自硬件统计，非估算 |
| **TRex**（脚本） | 降级 `{engine:"trex", script:filename, elapsed_s}` | **不估算**——脚本发包逻辑复杂，无法反推包数 |

> **关键约定**：dry-run 的 `measured=null`，前端必须明确标注「配置值（未实发）」，
> 不得与 live 的真实 BPS/PPS 混为一谈；Pktgen 统计 API 的字段名随版本略有差异，
> 接入时需对实际版本实测确认（`pkts_tx`/`mbits_tx` 或 `pkts_per_sec`/`mbits_per_sec`）。

---

## 6. 清洗设备集成（新增）

### 6.1 清洗设备接口

- 观测服务地址：`http://10.99.80.146:18181`。
- **启动观测**（已知接口）：

```http
POST /experiments/start
Content-Type: application/json

{
  "task_id": 1,
  "rules": [
    { "class_id": 1, "class_name": "business", "traffic_role": "business", "src_cidr": "20.2.0.0/16" },
    { "class_id": 2, "class_name": "attack",   "traffic_role": "attack",   "src_cidr": "30.1.0.0/16" }
  ]
}
```

- 语义：配置「被观测的攻击 IP 网段（`src_cidr`）」后，清洗设备据 `src_cidr` 区分业务与攻击流量，
  从而观测「清洗前流量（attack + business）」与「清洗后流量（business 放行）」。
- **读取流量**：**轮询 REST 拉取**（决策 #17）。具体读取接口路径对接清洗设备时确认，
  由适配层统一封装（见下），`spec` 不假设具体 URL。

### 6.2 清洗观测适配层（`backend/cleaner.py`）

```python
class CleanerAdapter:
    def start(self, task_id, attack_cidr, business_cidr) -> None   # POST /experiments/start
    def poll(self, task_id) -> CleanFlowSample                     # 轮询拉取，返回 before/after Mbps
    def stop(self, task_id) -> None                                # 停止观测（接口待确认）
```

- 生命周期：实验 `running` 启动时 `start()`；后台 asyncio 任务每秒 `poll()` 写 `clean_flows` 并推 WS `clean_flow`；实验结束 `stop()`。
- 清洗观测网段来自 `experiments.config`（创建实验时传入 `attack_cidr`/`business_cidr`），未配置则跳过清洗观测。
- 清洗设备不可达时**不中断实验**：记 error 日志 + 推 `storage_error`/降级，详情页清洗图显示「无数据」。

---

## 7. REST API

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/experiments?status=&cursor=&limit=` | 列表 |
| `POST` | `/api/experiments` | 创建实验（请求体含 `attack_cidr`/`business_cidr` 清洗观测网段） |
| `GET` | `/api/experiments/{id}` | 详情：`{experiment, attacks, probes, http_probes, clean_flows}`；`?after_seq=N` 增量返回 `events` |
| `GET` | `/api/experiments/{id}/events?after_seq=N&limit=` | 增量拉取事件（重连补齐） |
| `GET` | `/api/experiments/{id}/summary` | **总结页数据**：`{summary, config, attack_process, lessons}` |
| `POST` | `/api/experiments/{id}/stop` | 停止 |
| `DELETE` | `/api/experiments/{id}` | 软删除（queued/running 返回 409） |
| `GET` | `/api/meta/options` | 表单元数据（allowlist、工具清单、硬上限、模式选项） |
| `POST` | `/api/upload/pcap` | 上传（≤50MB），返回 `{file_path, file_name, size_bytes}` |

> `POST /api/experiments` 校验顺序：`target_ip ∈ allowlist` → `enabled_tools` 合法 →
> `tool_limits ≤ 硬上限` → `DEEPSEEK_API_KEY` 已配置 → PCAP 存在且 ≤50MB → 清洗网段格式合法。

---

## 8. WebSocket 协议（`/ws/{run_id}`）

- `seq` 与 `events.seq` 同源同值；第一个连接为操作员，后续为旁观。
- 事件类型（在旧版基础上新增 `http_probe`、`clean_flow`）：

| type | 载荷 | 说明 |
|------|------|------|
| `status` | `{status, run_id}` | 状态 |
| `reasoning` | `{seq, ts, content, reasoning_content, summary}` | 推理（折叠摘要） |
| `ai_message` | `{seq, ts, content}` | 纯文本 |
| `tool_call` | `{seq, ts, name, args}` | 工具调用 |
| `tool_result` | `{seq, ts, name, result}` | 工具结果 |
| `attack` | `{seq, ts, attack_type, attack_label, params, size, rtt}` | 攻击派生 |
| `probe` | `{ts, sent, received, avg_rtt_ms, loss_pct}` | ICMP 1s 聚合 |
| `http_probe` | `{ts, success_rate, avg_ttfb_ms, five_xx_rate, timeout_count}` | HTTP 1s 聚合 |
| `clean_flow` | `{ts, clean_before_mbps, clean_after_mbps}` | 清洗前后流量 1s |
| `hitl_request` / `hitl_response` | `{seq, ts, ...}` | HITL |
| `experiment_done` | `{status, summary}` | 结束 |
| `storage_error` / `error` | `{message}` / `{code, message}` | 降级告警 / 错误 |

前端上行：`{type:"hitl_response", data:{approved}}`、`{type:"stop_experiment"}`（仅操作员）。

---

## 9. 前端页面与交互

- **技术栈**：React + Vite + ECharts（npm）；暗色主题；可折叠侧边导航。
- **列表页**：表格/卡片 + 六态徽章 + 摘要 + 「新建实验」；5s 轮询。
- **新建**：`CreateExperimentModal` 弹窗，5 项配置分组，上限带硬上限提示，PCAP 上传 50MB 提示。
- **详情页**：左 3 图右 2 卡片（见 FR-3）；右栏内部滚动；「实验总结」按钮。
- **总结页**：四块内容（最终指标 KPI / 基本信息 / 攻击过程说明 / 经验教训总结）。
- **图表配色约定**：统一「绿 `#3ADF6E` + 橙 `#FFB547`」两色；攻击窗口 `markArea` 高亮。
- **截断摘要规则**：`summary = reasoning_content 前 80 字 + "…"`，空则用 `content` 前 80 字。

---

## 10. 经验教训生成

- **目标**：实验结束后，明确「对当前目标打什么攻击最有效」，指导下一次实验。
- **生成方式（决策 #18）**：规则统计 + 可选 LLM 叙述，复用 bugfix 分支的 lessons 管线：
  - `src/lessons/`（`extract.py` / `stats.py` / `records.py` / `render.py`）做规则统计；
  - `scripts/generate_lessons.py` 增量生成 `lessons/{run_id}.md`，可选 DeepSeek 叙述。
- **结论形态**：`lessons` 表行 `{title, text, attack_type, effectiveness}`，如
  「最有效手段：UDP 泛洪 —— rate≥80% 时 RTT 飙升 40 倍、丢包 74%」。

---

## 11. 决策记录

| # | 事项 | 决策 |
|---|------|------|
| 1 | 并发模型 | 单实验 + FIFO 排队，历史存多条 |
| 2 | 思考过程 | 全量入库 + 前端默认折叠 + 截断摘要（80 字） |
| 3 | 攻击大小量化 | Pktgen 统计 API 真实 BPS/PPS；dry-run 退化配置；TRex 降级脚本名+耗时 |
| 4 | 上限语义 | 每实验软上限 ≤ 全局硬上限 |
| 5 | 鉴权 | 暂不做 |
| 6 | 断线重连 | 继续跑 + 补齐续读 + HITL 恢复 |
| 7 | PCAP 归属 | 按实验归档 `data/uploads/{run_id}/` |
| 8 | 历史保留 | 暂不清理，全量保留 |
| 9 | 成功率与 RTT | 拆成 ICMP（RTT/丢包率）与 HTTP（成功率/TTFB）两类独立展示 |
| 10 | 删除语义 | 软删除 |
| 11 | 存储引擎 | SQLite + JSONL 审计日志 |
| 12 | 图表方案 | ECharts（npm 依赖） |
| 13 | PCAP 上限 | 50 MB |
| 14 | 100% 丢包 | 原样展示 + note 原文 |
| 15 | 重启恢复 | running/queued 标记 interrupted，不自动恢复 |
| 16 | events/派生表 | events 权威；attacks/probes/http_probes/clean_flows 派生 |
| 17 | 清洗流量获取 | **轮询 REST 拉取**；start 配置网段，读取接口对接时确认 |
| 18 | 经验教训 | 规则统计 + 可选 LLM 叙述，复用 lessons 管线 |
| 19 | 最终指标归属 | 移入总结页，详情页只做实时观测 |
| 20 | 技术栈 | React + Vite（弃用纯 HTML/JS/CSS） |

---

## 12. 边界与失败场景

| # | 场景 | 约定 |
|---|------|------|
| E1 | 无 API key / LLM 失败 | 创建时预检；运行中异常 → status=error，推 `error` |
| E2 | 目标 100% 丢包 | 原样展示 + note 原文 |
| E3 | Pktgen/TRex 连接失败 | 工具失败照常落库，攻击卡片失败态 |
| E4 | 服务端重启 | running/queued → interrupted |
| E5 | 运行/排队中删除 | 409 拒绝 |
| E6 | 取消排队 | 软删除即取消 |
| E7 | PCAP 超限 | 400 |
| E8 | 落库失败 | 不中断实验，推 `storage_error` |
| E9 | 多标签页 | 第一个 WS 为操作员，其余旁观 |
| E10 | 清洗设备不可达 | 不中断实验，清洗图显示「无数据」，记 error 日志 |
| E11 | 清洗读取接口变更 | 由 `backend/cleaner.py` 适配层统一封装，业务层无感 |

---

## 13. 分阶段实施建议

| 阶段 | 内容 | 产出 |
|------|------|------|
| **P0 数据层** | SQLite + events/attacks/probes/http_probes/clean_flows/lessons 建表 + 摘要 + 软删除 + 状态机 | `backend/storage.py` + 单测 |
| **P1 后端 API + 清洗适配** | `/api/experiments*` CRUD + `summary` + `meta/options` + `backend/cleaner.py`（start/轮询/stop） | REST + 单测 |
| **P2 实时事件** | WS 协议扩展 + attack/probe/http_probe/clean_flow 抽取 + 后台采集任务 + executor 化工具 | `experiment.py` + 集成测试 |
| **P3 前端接真** | `USE_MOCK=false`，对接 REST/WS；详情页 3 图 + 右栏；总结页 | 前端 + 联调 |
| **P4 总结/经验** | summary 计算 + 攻击过程说明派生 + lessons 生成 | `summary`/`lessons` + 单测 |
| **P5 加固** | 断线重连、排队、PCAP 归档、重启清理、多标签角色、清洗设备容错 | 端到端验证 |

---

## 14. 验收标准（对应 FR）

- [ ] FR-1：列表分页/过滤/软删除隐藏/5s 刷新正常；
- [ ] FR-2：5 项配置齐全；非法 IP / 超限 / 无 key / >50MB PCAP 均被后端拒绝；运行中创建进入排队；
- [ ] FR-3：详情页实时看到清洗前后流量、RTT/丢包率、HTTP 成功率/TTFB 三图 + 攻击时间线 + 推理流（折叠可展开）；
- [ ] FR-4：总结页四块（最终指标 + 基本信息 + 攻击过程 + 经验教训）齐全，历史可回看只读；
- [ ] FR-5：HITL 在详情页审批，决定落库审计；
- [ ] FR-6：断线重连后事件补齐无重复无遗漏，挂起 HITL 可恢复；
- [ ] FR-7：前一个实验结束后队首自动启动；
- [ ] FR-8：停止/取消/软删除语义正确；
- [ ] 安全回归：所有流量工具仍受硬上限 + allowlist 约束；
- [ ] 清洗集成：配置 attack 网段后，清洗前后流量按 1s 采样落库并实时推前端；清洗设备不可达时降级不中断实验。

---

*Spec v0.3 · 按当前 React 前端对齐重写 · 20 项决策已拍板 · 作为后端改造的唯一事实源。*
