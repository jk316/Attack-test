# 阶段 1 设计：数据模型 — 核心闭环 ReAct Agent 与运行模式

**特性**: `specs/001-agent-core/` | **日期**: 2026-11-19

## 实体

### 1. 实验运行（Experiment Run）

| 字段 | 类型 | 说明 | 校验规则 |
|------|------|------|----------|
| run_id | string | 本次运行唯一标识（现状为 8 位短 id） | 非空 |
| mode | enum | `experiment`（闭环实验）/ `catalog`（目录探索） | 二选一；由 `--trex-explore` 推导 |
| target_ip | string | 流量与 ping 的目标 | 必须 ∈ allowlist；启动前预检（D3） |
| max_iters | int | 最大轮数预算 | ≥1；默认 20，catalog 默认 40 |
| no_improve_limit | int | 连续无改善停止阈值 | ≥1；默认 5；仅 experiment 生效 |
| pcap_path | string | 可选 PCAP 画像路径 | 可空 |
| log_path | string | 实验结果 JSONL 路径 | 目录需存在/可创建 |
| instruction | string | 用户自由指令（注入 user message 与提示） | 可空 |
| profile | string? | 命名预设名 | 若给定必须存在于 experiment.json.profiles |
| best_reward | float | 历史最优奖励 | 初始 −inf 或 0，按统一公式更新 |
| consecutive_no_improve | int | 连续无改善计数 | 0 起；改善归零、无改善 +1（D5：观测不可靠不计） |
| iteration | int | 当前轮次 | 0 起 |

### 2. 迭代轮次（Iteration）

一轮「行动 → 观测 → 记录 → 决策」闭环单元。

| 字段 | 类型 | 说明 |
|------|------|------|
| iteration | int | 轮次号 |
| action | dict | 本轮流量动作（工具名 + 参数） |
| hitl_approved | bool | 本轮审批结果（实验模式） |
| observed | dict | 实测 avg_rtt_ms / loss_pct / covers_attack_window |
| reward | float | 按统一公式 `avg_rtt_ms + loss_pct × 10` 计算（D2） |
| logged | bool | 是否已写入 JSONL 日志 |

### 3. HITL 审批（HITL Approval）

| 字段 | 类型 | 说明 |
|------|------|------|
| message | string | 操作说明（如「[HITL] Approve traffic send?」） |
| params | dict | 待审批的参数明细（操作员所见即所批） |
| result | enum | `approved` / `rejected` / `auto_approved` / `default_rejected`（无输入） |

### 4. 参数配置（Parameter Configuration）

来源优先级链：**CLI 参数 > 命名预设 profile > experiment.json > 内置默认**。注入链：experiment.json → 环境变量 → 工具调用时读取（配置单一来源）。

| 分组 | 键 | 默认 |
|------|-----|------|
| 顶层 | target_ip / pcap_path / log_path / max_iters / no_improve_limit | 100.1.11.20 / "" / data/experiment.jsonl / 20 / 5 |
| attack | duration_s / pps / packet_size / flow_count / iat_jitter_ms | 10 / 100 / 64 / 1 / 0 |
| pktgen | rate / duration_ms | 50 / 10000 |
| trex | timeout_s | 30 |
| profiles | 命名预设（深合并 attack/pktgen/trex） | high_pps / long_run / pktgen_max |

### 5. 对话消息（Conversation Message）

| 字段 | 类型 | 说明 |
|------|------|------|
| role | enum | user / assistant / tool |
| content | string | 文本内容 |
| reasoning_content | string? | 模型推理内容；必须在后续轮请求中原样回传（FR-009） |
| tool_calls | list? | 工具调用（名称 + 参数） |

## 运行生命周期状态机（实验模式）

```text
[启动]
  → 预检（target∈allowlist、预算≥1、互斥组合）── 失败 → 报错非零退出
  → 构建（build_graph：模型 + 提示渲染 + 工具集 + 检查点）
  → 注入运行上下文（FR-003）
  → 循环：
      决策（模型）
        ├─ 提议流量工具 → [HITL 审批]
        │     ├─ 批准 → 执行 → 观测（rtt_during / read_ping_stats）
        │     │        → 记录（log_result）→ 裁决（更新 best_reward / 计数）
        │     └─ 拒绝 → 结果回传 → 决策（0 报文）
        ├─ 提议非流量工具 → 执行 → 观测
        └─ 输出总结 → [停止]
      裁决：consecutive_no_improve ≥ no_improve_limit 或 iteration ≥ max_iters → [停止]
  → 输出实验总结
  → 清理（停 ping 监控；目录模式写 catalog 摘要文件）
[结束]
```

目录探索模式差异：无 HITL 节点、无奖励计数；`iteration ≥ max_iters` 或图超步预算耗尽即停；最终消息写入 `output/trex_attack_catalog_<时间戳>.md`。

## 校验规则汇总

| 规则 | 出处 |
|------|------|
| target_ip ∈ allowlist（预检 + 工具层双重校验） | FR-017、002 规格 |
| max_iters ≥ 1、no_improve_limit ≥ 1 | FR-007、D3 |
| --trex-explore × --trex-live 互斥 | FR-012 |
| profile 名必须存在 | FR-015 |
| 无终端输入 → 审批默认拒绝 | FR-005 |
| 观测未覆盖攻击窗口（covers_attack_window=false）→ 不计入无改善判定 | D5 |
| 奖励公式唯一：`avg_rtt_ms + loss_pct × 10` | FR-016、D2 |
