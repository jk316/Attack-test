# 数据模型：Web 控制台（实时实验监控与人工审批）

**特性目录**: `specs/007-web-console/` | **日期**: 2026-11-19

> 注：本特性不引入持久化存储，以下实体为进程内内存模型（实验状态重启即失）。JSON 字段名沿用现状代码以降低改造风险。

## 实体

### 1. 控制台会话（ConsoleSession）

代表一个已连接的浏览器客户端（按 client_id 隔离，007-2 决议）。

| 字段 | 类型 | 说明 |
|------|------|------|
| client_id | string (8 位) | 客户端唯一标识，通道路径参数；前端生成（随机 UUID 前 8 位） |
| channel_state | enum | connecting → connected → disconnected |
| experiment | 实验运行 \| null | 本会话当前实验（单客户端会话模型：1 个会话至多 1 个运行中实验） |

校验规则：client_id 非空字符串；通道建立后即创建会话；断线时标记 disconnected 并释放通道资源（实验本身不因断线停止）。

### 2. 实验运行（ExperimentRun）

代表一次闭环实验。

| 字段 | 类型 | 说明 |
|------|------|------|
| thread_id | string | 实验图执行线程标识（8 位 UUID），用于状态追踪与前端展示 |
| target_ip | string (IPv4) | 目标 IP；默认值来自 experiment.json（单一来源，G4） |
| max_iters | int (≥1) | 最大迭代次数；默认 20 |
| no_improve_limit | int (≥1) | 无改善早停轮数；默认 5 |
| pcap_path | string | 已上传 PCAP 的存储路径（空 = 不使用画像） |
| log_path | string | 实验日志路径；默认 data/experiment.jsonl |
| state | enum | 见状态流转 |
| approval_queue | queue<审批决策> | HITL 决定队列（每次审批请求恰好消费一次） |
| owner_client_id | string | 会话所有者（审批/停止仅此客户端可操作，007-2） |

校验规则：target_ip 必须通过 allowlist 校验（实际发送时由工具执行，见 008-security-config）；max_iters/no_improve_limit 必须为正整数。

**状态流转**（state）：

```text
idle ──start──▶ starting ──▶ running ──┬─(完成/早停)──▶ done
   ▲                │      ▲           ├─(停止请求)────▶ stopped
   └────────────────┴──────┴───────────┴─(异常)────────▶ error
        （任何终态后复位为 idle）
   running 内部子状态：awaiting_approval（HITL 暂停；未获决定不得离开该子状态）
```

规则：仅 idle 可 start（否则拒绝：FR-009）；stopped/done/error 均为终态并复位为 idle；awaiting_approval 时只有审批决定或停止请求可推进。

### 3. 实时消息（ConsoleMessage）

推送单元的抽象，按类型区分。

| 字段 | 类型 | 说明 |
|------|------|------|
| type | enum | status / messages / tool_result / hitl_request / hitl_response / experiment_done / error |
| data | object | 依类型而异（见 contracts/ws-messages.md） |
| role | string \| null | 仅 messages：AI/用户/工具消息角色 |
| content | string | 消息文本（纯文本渲染，前端做转义） |
| tool_calls | array \| null | 工具调用列表（名称 + 参数快照） |

校验规则：所有消息必须 JSON 序列化安全；content 渲染前必须转义（防注入）；单条消息截断上限沿用现状（AI 1000 字符、工具结果 300 字符、摘要 2000 字符）并在契约中声明。

### 4. 人工审批请求（HitlRequest）

代表一次 HITL 门禁暂停（与 008-security-config 的审批决策契约对齐）。

| 字段 | 类型 | 说明 |
|------|------|------|
| message | string | 审批提示（如 "[HITL] Approve traffic send?"） |
| params | object | 参数快照（工具名、目标、数值参数） |
| decision | enum | pending → approved / rejected |
| consumed | bool | 决定是否已被队列消费（每请求恰好一次，防重复放行） |

校验规则：decision 只能由会话所有者客户端设置一次；重复/越权决定被忽略并返回错误提示（FR-012/FR-013）。

### 5. PCAP 上传文件（PcapUpload）

| 字段 | 类型 | 说明 |
|------|------|------|
| original_name | string | 原始文件名（仅展示用） |
| stored_name | string | 唯一存储名（8 位随机前缀 + 原始名，防覆盖/防路径穿越） |
| rel_path | string | 相对项目根路径，回填表单并供实验引用（如 data/uploads/xxxx_sample.pcap） |
| size_bytes | int | 字节大小 |
| ext | enum | pcap / pcapng / cap（不区分大小写） |

校验规则（007-3 决议，服务端强制）：扩展名 ∈ 白名单；大小 ≤ 100MB；校验失败不落盘并返回结构化错误。

## 实体关系

```text
控制台会话 1 ──── 0..1 实验运行（单客户端会话模型，007-2）
实验运行  1 ──── 0..N 实时消息（推送流）
实验运行  1 ──── 0..N 人工审批请求（每次 HITL 门禁一个，串行消费）
实验运行  0..1 ── 0..1 PCAP 上传文件（pcap_path 引用，非独占）
```

## 与宪法/规格的一致性说明（阶段 1 复查）

- 审批决定唯一来源 = 会话所有者点击按钮（宪法四：无自动放行路径）。
- 实验运行不存储任何门禁豁免字段（Web 端不存在 auto-approve 概念）。
- 默认值字段（target_ip/max_iters/no_improve_limit）由 experiment.json 单源注入（宪法六），数据模型不再定义第二份默认值表。
