# 前端需求整理 — 攻防智能体 Web 控制台（实验为中心）

> 整理自根目录 [`spec.md`](../spec.md)（v0.2 · 16 项决策已全部拍板 · 唯一事实源）：§5.1 信息架构、§6 功能需求、§7.5/7.8 攻击定义、§8 API 契约、§9 前端页面与交互、§10 思考链折叠、§15 验收标准。
> 实施范围对应：**Plan 2（前端三视图 + ECharts，spec §9）** + P4/P5 阶段的前端部分。

---

## 0. 现状 vs 目标（一句话）

| | 现状（`frontend/` 三件套） | 目标（本需求） |
|---|---|---|
| 结构 | **单次、单屏**：只有「消息流」面板 + 固定配置表单 | **实验为中心**：列表 → 新建 → 详情 → 历史回看 |
| 历史 | 无持久化，刷新即丢 | 每次实验一条可查询、可回放的记录 |
| 图表 | 无；统计卡（最佳 RTT / 最近 RTT）恒显「暂未采集」 | RTT + 成功率双轴实时曲线 + 攻击窗口高亮 |
| 推理 | `reasoning_content` 被丢弃不展示 | 思考链默认折叠（80 字摘要）可展开全文 |
| 攻击 | 无结构化展示 | 每次攻击一张卡片（类型 + 大小 + 窗口成功率 + HITL 状态） |

> ⚠️ 依赖提醒：新版前端依赖的新 REST/WS 契约（SQLite 持久化、`/api/experiments*`、`/ws/{run_id}` 事件流）属于后端 Plan 1，**尚未动工**。前端可先按契约用 mock 数据并行开发。

---

## 1. 信息架构（四条主线）

```
控制台
├── ① 实验列表页（默认首页）    历史实验表格/卡片 + 「新建实验」按钮
├── ② 新建实验页（表单）        5 项配置 → 点击「开始测试」
├── ③ 实验运行/详情页（实时+回看共用）
│      ├── 攻击时间线：攻击类型 / 攻击大小（每次攻击一张卡片）
│      ├── 推理流：智能体思考 → 文本 → 工具调用 → 结果 → HITL 决定
│      └── 拨测图表：RTT + 成功率双轴曲线 + 攻击窗口高亮
└── ④ HITL 审批（弹窗，嵌入详情页）
```

---

## 2. 页面需求

### 2.1 ① 实验列表页（默认首页）— FR-1

- 每行展示：实验短 ID、目标 IP、**状态徽章**、创建时间、结果摘要（最终 RTT / 拨测成功率 / 攻击次数 / 停止原因）。
- 状态徽章六态：`运行中 / 排队中 / 已完成 / 已停止 / 失败 / 中断`。
- 交互：按状态过滤、按时间倒序（默认）、游标分页；**每 5s 轮询**刷新状态与摘要；「新建实验」入口；软删除按钮（queued/running 禁用）。

**AC**：① N 条实验按 `created_at` 倒序分页显示、字段齐全；② 六态任一过滤只显示该状态；③ 软删除行消失；④ running 实验服务端结束后 5s 轮询内该行状态与摘要自动更新。

### 2.2 ② 新建实验页（表单，5 项配置）— FR-2

| # | 配置项 | 说明 | 默认来源 |
|---|--------|------|---------|
| 1 | **攻击 IP** | 下拉给出 `allowlist.json` 的 hosts[]，允许手动输入但后端强校验 | allowlist.json |
| 2 | **用户提示词** | 自由文本，注入 user message 与 system prompt | 空 |
| 3 | **攻击工具上限** | 每实验**软上限**（≤ 硬上限常量）：pps、duration_s、packet_size、flow_count、pktgen rate/duration 等 | experiment.json |
| 4 | **工具开关** | 按类别分组勾选（Scapy / Pktgen / TRex），未勾选不注册进图 | 全选 |
| 5 | **业务 PCAP 上传** | ≤ 50 MB，创建时按实验归档到 `data/uploads/{run_id}/` | 可选 |

- 前端即时校验：上限输入带**硬上限提示**（从 `/api/meta/options` 拉取）；PCAP 50MB 提示。
- 提交成功 → 跳详情页；已有实验 running 时 → 提示「已加入排队」。
- 后端 400 时展示具体错误（非法 IP / 超上限 `{param, given, hard_limit}` / 无 API key / PCAP 超限）。
- 额外配置（max_iters、no_improve_limit、运行模式等）默认不暴露，保留现有能力。

### 2.3 ③ 实验运行/详情页（核心，三栏或分 Tab）— FR-3

**1) 攻击时间线**：每次攻击一张卡片——
- 类型标签：工具名 + 友好中文标签（19 工具 → 归一化映射，见 spec §7.8，如 `pktgen_udp_flood` →「Pktgen UDP 泛洪」，TCP 附 flags、range_scan 附 scan_field）；
- 大小数值：归一化强度（engine / pps 或 rate% / duration_s / packet_size / flow_count / est_total_packets / est_mbps）；Pktgen live 显示**真实 BPS/PPS**（measured），dry-run 显示配置值，TRex 降级为脚本名 + 耗时（spec §7.5）；
- 该攻击窗口成功率（`attacks.rtt`）；
- HITL 状态；失败攻击显示灰色卡片 + 错误信息；
- `observation_window.covers_attack_window=false` 时显示**警告标记 + note 原文**。

**2) 推理流（时序）**：`reasoning`（**默认折叠为 80 字截断摘要，点击展开全文**）→ `ai_message` 文本 → `tool_call`/`tool_result`（可展开）→ `hitl` 决定。按 `seq` 顺序渲染。

**3) 拨测图表**：**ECharts 双 Y 轴折线**——左轴 RTT(ms)、右轴成功率(%)；攻击窗口用 `markArea` 高亮；面板同时显示 avg/min/max RTT、丢包率、成功率数字。

- 实时性：事件产生后 ≤1s 内按 seq 渲染。
- 100% 丢包：原样展示「丢包率 100% / 成功率 0%」+ `observation_window.note` 原文，**不强行定性**。

### 2.4 ④ 历史回看 — FR-4（与运行详情页共用 UI）

- completed/stopped/error/interrupted 实验为**只读回放**：一次性加载完整事件按 seq 顺序渲染。
- 回放页**不出现** HITL 按钮等交互控件。

### 2.5 HITL 审批弹窗 — FR-5（保留并增强）

- 详情页内弹窗，展示**将要实发的参数**；TRex 含脚本预览 + 危险提示。
- 批准/拒绝经 WS 上行 `hitl_response`；决定作为 `hitl` 事件落库并回显所有连接。
- 断线时实验保持挂起，重连后重新弹出未决审批框。

### 2.6 断线重连 — FR-6（前端部分）

- 实验跑在后端进程，浏览器刷新/断网**实验不停**。
- 重连流程：`/ws/{run_id}` 重连 → `GET /api/experiments/{id}?after_seq=本地最后seq` 补齐断线事件（回放）→ WS 增量续播（直播）；对齐**只认 seq**，无重复无遗漏。
- 断线时存在待决 HITL → 重连后重新弹出；断线期间已结束 → 补齐后显示结束状态与摘要。

### 2.7 排队 / 停止 / 软删除交互 — FR-7 / FR-8（前端部分）

- running 时新建实验 → 提示「已加入排队」（queued）。
- queued 可取消（软删除）；running 有「停止」按钮；queued/running **禁用删除按钮**（后端 409 兜底）。

---

## 3. 技术栈与工程约束

| 约束 | 内容 |
|------|------|
| 技术栈 | **纯 HTML / JS / CSS，无构建步骤、无框架**（沿用现状）；桌面浏览器 |
| 图表 | **ECharts 本地 vendor**（`frontend/vendor/echarts.min.js`），不依赖外网，如需 CDN 可一行切换 |
| 主题 | 暗色主题延续（具体视觉风格 spec 未定，见 §6 待确认） |
| 安全 | 无鉴权（已决策）：保留「仅限可信内网使用」警告横幅；所有内容渲染前 **HTML 转义**（防注入） |
| 渲染截断 | 沿用 007 契约：AI 正文 ≤1000 字、工具结果 ≤300 字、摘要 ≤2000 字、tool_call 徽章参数 ≤60 字（全量在 DB/WS 原文可查） |
| 折叠摘要 | `summary = 去换行归一化的 reasoning_content 前 80 个 Unicode 字符 + "…"`；reasoning 为空时用 content 前 80 字 |

---

## 4. 前端消费的 API（契约摘要，详见 spec §8）

**REST**：

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/api/experiments?status=&cursor=&limit=` | 列表（六态过滤 + 游标分页） |
| POST | `/api/experiments` | 创建实验（5 项配置 + 校验），返回 `{run_id, status}` |
| GET | `/api/experiments/{id}` | 详情 `{experiment, attacks, probes}`；`?after_seq=N` 增量事件 |
| GET | `/api/experiments/{id}/events?after_seq=N&limit=` | 断线重连补齐事件 |
| POST | `/api/experiments/{id}/stop` | 停止 running |
| DELETE | `/api/experiments/{id}` | 软删除（queued/running → 409） |
| GET | `/api/meta/options` | 表单元数据：allowlist hosts、工具清单（分类/默认值/硬上限）、模式选项 |
| POST | `/api/upload/pcap` | 上传 PCAP（≤50MB） |

**WebSocket `/ws/{run_id}`**（下行，`seq` 与 `events.seq` 同源同值）：

`status` / `reasoning`（含折叠摘要） / `ai_message` / `tool_call` / `tool_result` / `attack`（卡片数据） / `probe`（每秒聚合点，供曲线） / `hitl_request` / `hitl_response` / `experiment_done`（含摘要） / `storage_error` / `error`。

**上行**：`{type:"hitl_response", data:{approved}}`、`{type:"stop_experiment"}`（仅「操作员」连接——第一个连接该 run 的 WS；其余为旁观，发控制消息收 `error: not_operator`）。

---

## 5. 状态徽章与视觉语义（建议）

| 状态 | 徽章建议 |
|------|---------|
| running 运行中 | 绿色 / 脉冲动画 |
| queued 排队中 | 蓝色 |
| completed 已完成 | 绿色（静态） |
| stopped 已停止 | 灰色 |
| error 失败 | 红色 |
| interrupted 中断 | 橙色 |

> 颜色为实施建议，spec 未强制；具体视觉规范见 §6。

---

## 6. 待与用户确认（spec 未覆盖的视觉细节）

spec 只确定了「暗色主题 + 页面结构」，**没有**具体视觉规范。需要确认：

1. 整体布局：侧边导航 + 内容区，还是顶部 Tab 导航？（spec §9 允许「三栏或分 Tab」）
2. 视觉风格参考：有没有喜欢的工具/产品界面（如 Grafana / K8s Dashboard / 其他安全平台）？
3. 配色：延续当前暗色，还是指定主色（品牌色/强调色）？
4. 攻击卡片的信息密度：紧凑（一行卡片）还是详细（展开式）？

---

## 7. 现状 → 目标差距清单（前端文件）

| 现状（旧三件套） | 目标 | 涉及 |
|-----------------|------|------|
| `index.html` 单屏：消息流 + 固定表单 | 三视图（列表/新建/详情）+ HITL 弹窗 | 全部重写 |
| `app.js` 单 WS 连接（`/ws/{client_id}`）、无路由 | 路由式多视图 + `/ws/{run_id}` + 5s 轮询 + 断线续读 + 操作员/旁观角色 | 全部重写 |
| `style.css` 基础暗色样式 | 设计系统（色板/徽章/卡片/图表/弹窗变量化） | 全部重写 |
| 无图表 | `frontend/vendor/echarts.min.js` 本地引用，双轴曲线 + markArea | 新增 |
| 统计卡恒显「暂未采集」 | 数据源接 `tool_result`/`experiment_done`/`probes` | 重写 |

---

## 8. 验收标准（前端相关，摘自 spec §15）

- [ ] FR-1：列表分页/过滤/软删除隐藏/5s 状态刷新正常；
- [ ] FR-2：5 项配置齐全；非法 IP / 超限上限 / 无 API key / >50MB PCAP 均有明确报错；运行中创建进入排队；
- [ ] FR-3：实时看到攻击类型、攻击大小（Pktgen live 含真实 BPS/PPS）、推理过程（折叠摘要可展开）、RTT + 成功率双轴曲线；
- [ ] FR-4：历史实验完整回放、只读；
- [ ] FR-5：HITL 在详情页审批，决定落库审计；
- [ ] FR-6：刷新/断线重连后事件补齐无重复无遗漏，挂起 HITL 可恢复审批；
- [ ] FR-7：前一个实验结束后队首自动启动；
- [ ] FR-8：停止/取消/软删除语义正确；软删除后数据仍在库中。

---

## 9. 实施顺序与依赖

```
Plan 1（后端核心，未开始）：P0 SQLite 持久化 → P1 REST API → P2 实时事件/WS 协议
Plan 2（本前端，本次范围）：P3 三视图 + 新建表单 + 详情页 + HITL 弹窗 + ECharts vendor
                          P4 历史回看（回放/过滤/分页/软删除交互）
                          P5 断线重连交互 + 多标签角色提示
```

- 前端对后端契约已完全冻结（spec §8），可**先用 mock 数据并行开发**，后端就绪后直接对接。
- 验收以 spec §15 清单为准，安全回归（硬上限 + allowlist）不受前端影响。
