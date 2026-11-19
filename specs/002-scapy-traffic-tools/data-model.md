# 阶段 1 设计：数据模型 — Scapy 流量工具集

**特性**: `specs/002-scapy-traffic-tools/` | **日期**: 2026-11-19

## 实体

### 1. 流量发送参数集（Send Parameters）

| 字段 | 类型 | 范围/规则 | 说明 |
|------|------|-----------|------|
| dst_ip | string | 必须 ∈ allowlist；格式合法；非广播/组播 | 目标（FR-002） |
| dst_port | int | 1–65535 | 越界拒绝（FR-006） |
| duration_s | int | >0；超 20 钳制为 20 | 发送时长（FR-004/005） |
| pps | int | >0；超 20000 钳制为 20000 | 总速率（FR-004/005） |
| packet_size | int | >0；超 1024 钳制为 1024 | 负载字节（traffic_send） |
| flow_count | int | >0；超 100 钳制为 100 | 并发流数（traffic_send） |
| iat_jitter_ms | int | ≥0；超 20 钳制为 20 | 间隔抖动；mixed 亦支持（002-2） |
| src_ip | string? | 只允许空；非空即拒绝 | 反源伪造（FR-003） |

区分**请求值（requested_params）**与**实际值（params）**：钳制只改数值参数，安全违规直接拒绝（002-1）。

### 2. 流量规格（Traffic Spec）— mixed_traffic_send 输入

```text
traffic_spec_json: string（JSON，≤10000 字符）
└─ streams: list[Stream]，1–100 条
   ├─ stream_id: string，非空、唯一
   ├─ protocol_stack: list[string]，非空，仅限 {IP, TCP, UDP, ICMP, DNS, Raw}
   ├─ fields: dict[协议名 → dict]，值须通过危险模式扫描（FR-013）
   └─ percentage: int 1–100 | 缺失 → 平均补齐；总和必须 100（FR-012）
```

| 规则 | 出处 |
|------|------|
| IP.dst 一律忽略，强制覆盖为工具参数 dst_ip | FR-011 |
| 缺百分比：`(100 − 显式之和) / 缺失数` 均分，余数依次 +1；显式之和 ≥100 时拒绝 | FR-012 |
| 重复 stream_id / 协议越白名单 / 嵌套字段越白名单 | 拒绝（FR-010） |
| 注入特征（eval/exec/import/os/subprocess/open 等模式） | 拒绝整规格（FR-013） |

### 3. 发送结果（Send Result）— traffic_send / mixed_traffic_send 输出

| 字段 | 类型 | 说明 |
|------|------|------|
| success | bool | 流程是否成功（HITL 拒绝为 false + error） |
| params | dict | 钳制后实际生效参数（mixed 含 streams 百分比补全结果） |
| requested_params | dict | 原请求值（002-1 新增） |
| clamped | list[string] | 被钳制的字段名列表，空 = 未钳制（002-1 新增） |
| packets_sent | dict | total + per_flow / per_stream |
| elapsed_s | float | 实际耗时 |
| effective_pps | float | 实际速率 |
| send_mode | enum | raw / udp / scapy（traffic_send） |
| raw_socket | bool | 是否使用高权限通道（mixed） |
| completed | bool | 是否完整发送；中断为 false（002-3 新增，缺省 true） |
| interrupt_reason | string? | completed=false 时的原因（002-3 新增） |
| errors | list | 错误明细（保留位） |
| rtt_during / attack_window / observation_window | object | 观测字段（003 规格结构，FR-019） |

### 4. RTT 探测结果（Ping Result）

| 字段 | 类型 | 说明 |
|------|------|------|
| success | bool | 全丢包时仍为 true（avg=inf 表达） |
| avg_rtt_ms | float | 平均值；全丢包 = +inf |
| loss_pct | float | 0–100 |
| packets_transmitted / packets_received | int | 收发计数 |
| raw_output | string | 探测原始输出（诊断） |
| error | string? | 失败原因（命令缺失/超时） |

### 5. 实验日志条目（Log Entry）— log_result 输出

```json
{"iteration": 3, "params": {...}, "rtt": 12.5, "loss": 0.0, "timestamp": "2026-11-19T01:00:00+00:00"}
```

| 规则 | 出处 |
|------|------|
| 单行 JSON 追加写入；父目录不存在 → 返回失败且不创建文件 | FR-016 |
| 时间戳 UTC ISO 8601 | FR-016 |

## 发送生命周期状态机

```text
[调用]
  → 参数解析：env 默认 → 请求值（requested_params 记录）
  → 校验：
      安全类（allowlist/格式/广播/组播/端口/源伪造）── 违规 → 拒绝（0 报文）
      数值类 → 钳制（生成 params + clamped 标注）
  → HITL 审批（traffic_send / mixed_traffic_send）
        ├─ 拒绝 → {success:false, error:"HITL rejected"}（0 报文）
        └─ 批准 → 构建报文（mixed：规格校验→模板字节流→CDF）
  → 发送循环：选流（轮转 / 加权随机）→ 发送 → 抖动调度 → 直到 deadline
        └─ 中断（Ctrl-C）→ 停止循环，completed=false + interrupt_reason
  → 汇总：packets_sent / elapsed_s / effective_pps / send_mode
  → 合并观测字段（rtt_during / attack_window / observation_window）
[返回]
```

## 校验规则汇总（FR 对照）

| FR | 规则 |
|----|------|
| FR-002 | validate_target：allowlist ∈ / 格式 / 非广播 / 非组播 |
| FR-003 | src_ip 非空拒绝 |
| FR-004 | 五类数值上限钳制（pps/duration/packet_size/flow_count/jitter） |
| FR-005 | 非正数/负抖动拒绝 |
| FR-006 | dst_port 1–65535 |
| FR-007 | 流间互异源端口（1024+ 序号）+ 轮转 |
| FR-009 | HITL 拒绝 0 报文 |
| FR-010/011/012/013 | 规格校验四件套（白名单/覆盖/百分比/注入） |
| FR-014 | 加权随机选流 + per_stream 计数 |
| FR-015 | 全丢包 inf、命令缺失/超时失败 |
| FR-016 | JSONL 追加 + UTC 时间戳 + 目录缺失失败 |
| FR-017 | env 默认、调用时读取 |
| FR-018 | 文档上限 = 常量上限 |
| FR-019 | 观测字段附带 |
