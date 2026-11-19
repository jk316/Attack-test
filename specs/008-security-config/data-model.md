# 数据模型：安全约束与配置体系（横切关注点）

**特性目录**: `specs/008-security-config/` | **日期**: 2026-11-19

> 本特性无持久化存储与运行态对象（校验为纯函数、配置为静态文件）；下述「实体」指全项目共享的**契约型**概念。

## 实体

### 1. 安全策略（SecurityPolicy）

全项目共享、宪法级固定的安全边界，唯一事实来源。

| 组成 | 内容 | 管理方式 |
|------|------|---------|
| 白名单条目 | IPv4 列表（allowlist.json 的 hosts 数组） | 唯一文件管理；import 时加载；空/缺失 → 校验失败关闭 |
| 参数上限常量 | pps=20000、duration_s=20、packet_size=1024、flow_count=100、iat_jitter_ms=20、MAX_STREAMS=100、Pktgen rate≤100%、Pktgen duration≤60000ms | 硬编码常量（宪法附加约束）；不纳入配置 |
| 门控矩阵 | 见下表 | 与代码常量同步维护（文档真实性） |

**门控矩阵**（allowlist / HITL 二维，与宪法、CLAUDE.md 一致）：

| 入口 | allowlist | HITL |
|------|:---:|:---:|
| Scapy traffic_send / mixed_traffic_send / ping_rtt / start_ping_monitor | ✅ | ✅（发送类）/ ❌（测量类） |
| Pktgen udp/tcp/icmp_flood、range_scan、packet_sequence | ✅ | ✅（live）/ ❌（dry-run） |
| Pktgen arp_flood | ❌（L2 无 IP） | ✅（live） |
| Pktgen pcap_replay | ❌（PCAP 自带目标，提示警告） | ✅（live） |
| Pktgen stats_monitoring / safe_stop_and_reset | N/A | ❌（无流量） |
| TRex write_python_file | N/A（仅写文件+语法检查） | ❌ |
| TRex run_python_file | 实发前：目标参数校验 + 脚本静态扫描 | ✅（live）/ ❌（dry-run） |
| TRex explore 模式 | 结构上仅 2 个写/检查工具 | ❌（零流量零审批） |

### 2. 目标校验（TargetValidation）

纯函数契约 `validate_target(ip)`，所有流量工具统一复用。

| 检查顺序 | 规则 | 失败后果 |
|---------|------|---------|
| 1 白名单非空 | allowlist 为空 → fail | 拒绝（"allowlist is empty"） |
| 2 格式 | 合法 IPv4 | 拒绝（"Invalid IP format"） |
| 3 广播 | 不以 .255 结尾 | 拒绝 |
| 4 组播 | 首段 ∉ [224, 239] | 拒绝 |
| 5 归属 | ip ∈ allowlist | 拒绝（"Target … not in allowlist"） |

失败关闭（fail-closed）：任何一步失败即抛错，调用方不得发包。

### 3. 实验配置（ExperimentConfig）

`src/config/experiment.json` 的结构化契约（详见 [contracts/experiment-config.md](contracts/experiment-config.md)）。

| 字段组 | 内容 | 约束 |
|--------|------|------|
| 顶层 | target_ip、pcap_path、log_path、max_iters、no_improve_limit | max_iters/no_improve_limit 为正整数 |
| attack | duration_s、pps、packet_size、flow_count、iat_jitter_ms | 各自 ≤ 对应上限常量（超限仅告警+钳制，见 G2） |
| pktgen | rate、duration_ms | 0≤rate≤100；duration_ms≤60000（G4 钳制后） |
| trex | timeout_s | (0, 300]（trex/config.py 已钳制） |
| profiles | 命名预设 → 覆盖字段组 | 未知名报错并列出可用（main.py 已实现） |

**优先级**: 显式 CLI > profiles > 基础配置 > 工具签名 fallback（FR-014）。上限恒为最终裁决层。

### 4. 审批决策（ApprovalDecision）

| 字段 | 类型 | 说明 |
|------|------|------|
| message | string | 统一提示（如 "[HITL] Approve traffic send?"） |
| params | object | 完整参数快照（统一明细格式，008-3） |
| scope | enum | scapy_traffic / pktgen_traffic / trex_script |
| source | enum | human_approve / human_reject / auto_approve（仅 CLI --auto-approve 且不与实发组合，G1） |

规则：CLI 阻塞式 input 与 Web 队列回填均映射到同一布尔决定 `resume(approved)`；拒绝 → 工具返回失败且零流量；dry-run 不产生审批请求。

### 5. 运行模式（RunMode）

| 模式 | 流量 | 审批 | 组合约束（G1 后） |
|------|:---:|:---:|------|
| dry-run（默认，Pktgen/TRex） | 无 | 无 | 可与任意参数组合 |
| live（--pktgen-live / --trex-live） | 有 | 每次发送必审 | **禁止与 --auto-approve 组合（启动报错）** |
| auto-approve | 视模式 | 自动批准并标记 | 仅限 dry-run 语境 |
| explore（--trex-explore） | 无 | 无 | 与 --trex-live 互斥（既有） |

## 状态流转 / 互斥状态机

```text
[启动参数解析] ──▶ 互斥校验（G1 实现后）
   auto_approve ∧ (pktgen_live ∨ trex_live)  → ERROR 退出
   trex_explore ∧ trex_live                  → ERROR 退出（既有）
   ├─ 通过 → 配置校验层（G2）：默认值超限 → 逐项 WARN（钳制后值）
   └─ 进入实验循环 → 工具调用 → 校验链（allowlist→格式→广播/组播→src_ip→上限钳制）
                                → 流量工具 ∧ live → interrupt()（统一审批契约）
                                    ├─ approved → 发送（仍受上限）
                                    └─ rejected → 中止，零流量
```

## 与宪法/规格的一致性说明（阶段 1 复查）

- 门控矩阵与上限数值逐项对照宪法「附加约束」与 CLAUDE.md「Key Conventions」，0 冲突。
- 审批决定的三个来源（人批/人拒/自动批准）中，自动批准被 G1 限制为不可能与真实流量共存——宪法四无豁免路径。
- 配置优先级链的最终裁决层是常量上限而非配置值——原则四优先于原则六（默认值可配、边界不可配）。
