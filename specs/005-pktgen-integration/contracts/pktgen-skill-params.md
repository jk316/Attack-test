# 契约：Pktgen 技能参数与门控规则

**特性目录**: `specs/005-pktgen-integration/` | **日期**: 2026-11-19

**契约性质**: 本契约描述 9 个 Pktgen 工具的**外部行为契约**。参数默认值与编译期约束的语义唯一来源是 `dsl/skills/*.yaml`（vendored，不改动）；「适配器门控」列是 `src/pktgen/adapter.py` 在编译前后追加的规则（本特性 G1–G5 的落地口径）。

## 1. 通用门控规则（适配器层，适用于所有 9 个工具）

| 规则 | 触发条件 | 行为 |
|------|---------|------|
| RATE_LIMIT | rate 参数 >100 或 <0 | 编译期 CompileError，返回参数错误（FR-008） |
| DURATION_LIMIT | duration > 60000 ms | 适配器拒绝：`success=false, error=参数错误`（G1/FR-009）；duration=0 合法（永久发包，需 stop_and_reset 终止） |
| SRC_IP_FORBIDDEN | 传入 src_ip 参数（非省略） | 适配器拒绝：`success=false, error=src_ip 不允许自定义`（G3/FR-016） |
| ALLOWLIST | 见下表 dst_ip 列 | `validate_target`：IP 格式 → 广播/组播 → 白名单，任一失败即拒绝（FR-005/FR-016） |
| HITL | live 模式且技能属 7 个流量技能 | `interrupt()` 审批；拒绝 → `success=false, error=HITL rejected by operator`（FR-006） |
| DRY_RUN | 默认（未设 `--pktgen-live`） | 仅编译+保存产物，零连接零流量（FR-004） |

## 2. 逐技能参数契约

单位约定：rate 为线速百分比（0–100）；duration 为毫秒；pktSize 为字节（64–1518）；count=0 表示永久。

### 2.1 udp_flood / tcp_flood / icmp_flood

| 参数 | 类型 | 必填 | 默认（YAML） | 约束 | 适配器门控 |
|------|------|:---:|------|------|-----------|
| rate | float | ✅ | — | 0–100 | RATE_LIMIT |
| dst_ip | ip | ❌ | 10.10.10.2 | — | 非空 + ALLOWLIST（FR-005） |
| duration | int | ❌ | 0 | — | DURATION_LIMIT |
| pktSize | int | ❌ | 256（icmp 64） | 64–1518 | — |
| count / burst | int | ❌ | 0 / 128 | — | — |
| src_ip | string | ❌ | 192.168.1.1/24 | — | SRC_IP_FORBIDDEN |
| sport / dport | int | ❌ | 1234 / 5678 | — | — |
| tcp_flags（仅 tcp） | string | ❌ | ack | fin,syn,rst,psh,ack,urg,ecn,cwr 组合 | — |
| ttl（仅 icmp） | int | ❌ | 64 | — | — |

### 2.2 arp_flood

| 参数 | 类型 | 必填 | 默认 | 约束 | 适配器门控 |
|------|------|:---:|------|------|-----------|
| rate | float | ✅ | — | 0–100 | RATE_LIMIT |
| duration | int | ❌ | 0 | — | DURATION_LIMIT |
| arp_type | enum | ❌ | request | request/req/gratuitous/grat/g | — |
| count / burst | int | ❌ | 0 / 128 | — | — |
| dst_ip | string | ❌ | 空 | 仅用于 RTT 采样，不下发硬件 | **提供时必须过 ALLOWLIST**（G2/决策 005-3）；为空则跳过 RTT 采样 |

### 2.3 range_based_scan

| 参数 | 类型 | 必填 | 默认 | 约束 | 适配器门控 |
|------|------|:---:|------|------|-----------|
| scan_field | enum | ✅ | — | dst_ip/src_ip/dst_port/src_port/dst_mac/src_mac/vlan_id/pkt_size | — |
| start / min / max / inc | any | ✅ | — | 逐包递增、min↔max 回绕；inc=0 不变化 | — |
| dst_ip | ip | ✅ | — | — | 非空 + ALLOWLIST（FR-005） |
| rate | float | ❌ | 50 | 0–100 | RATE_LIMIT |
| pktSize | int | ❌ | 128 | 64–1518 | — |
| count | int | ❌ | 0 | — | — |

### 2.4 packet_sequence_generation

| 参数 | 类型 | 必填 | 默认 | 约束 | 适配器门控 |
|------|------|:---:|------|------|-----------|
| sequences | table(JSON 数组) | ✅ | — | ≤16 条目；每条目必含 eth_dst_addr/eth_src_addr/ip_dst_addr/ip_src_addr/sport/dport/ethType/ipProto/vlanid/pktSize，可选 teid/cos/tos/tcp_flags | 非法 JSON → 拒绝（FR-013）；eth_dst_addr 缺失/空/全 0-1 模式 → 替换为 topology dst_mac 并记 `replaced_mac`（FR-012/G5） |
| dst_ip | ip | ✅ | — | — | 非空 + ALLOWLIST（FR-005） |
| rate | float | ❌ | 100 | 0–100 | RATE_LIMIT |
| count / burst | int | ❌ | 0 / 128 | — | — |

### 2.5 pcap_replay

| 参数 | 类型 | 必填 | 默认 | 约束 | 适配器门控 |
|------|------|:---:|------|------|-----------|
| pcap_file | string | ✅ | — | **Pktgen 主机本地路径**（Agent 侧不校验存在性） | 免 ALLOWLIST（PCAP 自带目标，FR-005） |
| rate | float | ❌ | 100 | 0–100 | RATE_LIMIT |
| count | int | ❌ | 0 | 0=整个文件循环 | — |

### 2.6 stats_monitoring

| 参数 | 类型 | 必填 | 默认 | 约束 | 适配器门控 |
|------|------|:---:|------|------|-----------|
| interval_ms | int | ❌ | 1000 | — | 免 HITL（FR-007）；dry-run 下仅编译（决策 005-2） |
| iterations | int | ❌ | 10 | 0=持续到中断 | 同上 |
| mode | enum | ❌ | all | all/link/sending/rates/packets/port | 同上 |

### 2.7 safe_stop_and_reset

| 参数 | 类型 | 必填 | 默认 | 约束 | 适配器门控 |
|------|------|:---:|------|------|-----------|
| save_config | bool | ❌ | false | — | 免 HITL、可随时调用（FR-007）；dry-run 下仅编译（决策 005-2） |
| clear_stats | bool | ❌ | true | — | 同上 |
| reset_ports | bool | ❌ | true | — | 同上 |

## 3. 变更影响说明

- 本契约中的 DURATION_LIMIT、SRC_IP_FORBIDDEN、arp dst_ip ALLOWLIST、replaced_mac 是计划缺口 G1–G5 的目标口径，当前实现尚未全部满足（见 [plan.md](../plan.md) 实施阶段）。
- YAML 默认值列仅供文档对照；vendored 文件不得修改（宪法附加约束）。
