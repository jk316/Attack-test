# 数据模型：Pktgen-DPDK 硬件集成

**特性目录**: `specs/005-pktgen-integration/` | **日期**: 2026-11-19

实体来自 spec.md「关键实体」节，字段与校验规则以现状实现 + 计划缺口（G1–G5）为准。

## 实体 1：Pktgen 技能（Skill）

代表 9 个技能定义，语义唯一来源为 `dsl/skills/*.yaml`（vendored，本特性不改动）。

| 字段 | 类型 | 说明 |
|------|------|------|
| name | string | 技能名：udp_flood / tcp_flood / icmp_flood / arp_flood / range_based_scan / packet_sequence_generation / pcap_replay / stats_monitoring / safe_stop_and_reset |
| intent | enum | traffic_generation / traffic_scanning / packet_crafting / monitoring / control |
| params | list | 每个参数：name、type（string/integer/float/boolean/enum/mac_address/ip_address/portlist/table）、required、default、constraints（min/max/enum） |
| setup / plan / teardown | list | 编译步骤（引用 `$topology.*`、`$params.*` 占位符） |

**校验规则（编译期，现状已实现）**: required 缺失拒绝；类型不符拒绝；min/max 越界拒绝（含 rate 0–100）；enum 取值非法拒绝。

**本特性新增校验（适配器层，G1/G3/G4）**: duration>60000 拒绝（G1，0 仍合法）；LLM 传入 src_ip 拒绝（G3）；rate/duration 缺省时调用时读 env（G4）。

## 实体 2：攻击请求（Attack Request）

代表 Agent 发起的一次工具调用。

| 字段 | 类型 | 说明 |
|------|------|------|
| skill_name | string | 见实体 1 |
| params | dict | 参数集合；None 值在编译前剥离 |
| dst_ip | string \| null | 目标 IP；不同技能语义不同（见门控矩阵） |
| mode | enum | dry_run（默认）/ live（`--pktgen-live`） |

**门控矩阵（适配器层）**:

| 技能 | dst_ip 必需 | allowlist | HITL（仅 live） | src_ip 禁止 | duration 上限 |
|------|:---:|:---:|:---:|:---:|:---:|
| udp/tcp/icmp_flood | ✅ | ✅ | ✅ | ✅ | ✅ |
| arp_flood | ❌（提供则必须过 allowlist） | ✅（提供时） | ✅ | N/A | ✅ |
| range_based_scan / packet_sequence_generation | ✅ | ✅ | ✅ | N/A | N/A |
| pcap_replay | ❌（PCAP 自带目标） | ❌ | ✅ | N/A | N/A |
| stats_monitoring / safe_stop_and_reset | N/A | N/A | ❌ | N/A | N/A |

**状态流转**: 调用 → 参数前置校验（G1/G3，失败即止）→ dst_ip 校验（需 allowlist 的技能 / arp 提供时；失败即止）→ HITL（live 且属 7 个流量技能；拒绝即止）→ 编译执行（dry-run：编译+保存；live：编译+TCP 下发）→ 同步等待（live，min(duration,60000)ms）→ RTT 采样（带 dst_ip 时）→ 归一化返回。

## 实体 3：编译产物（Compiled Script）

| 字段 | 类型 | 说明 |
|------|------|------|
| content | text | 编译生成的完整脚本（Pktgen 可执行） |
| path | string | `lua_scripts/<YYYYMMDD_HHMMSS>_<skill_name>.lua`（时间戳防覆盖） |
| mode | enum | 保存时的执行模式（dry_run / live） |

结果中只返回 path + 前 200 字符预览（`lua_preview`），不返回全文（上下文预算保护）。

## 实体 4：工具结果（Tool Result）

统一结构（FR-015 + 缺口 G5）：

| 字段 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| success | bool | ✅ | 编译/下发是否成功 |
| skill | string | ✅ | 技能名 |
| mode | enum | ✅ | dry_run / live / unknown（异常时） |
| error | string | 条件 | 失败原因原文 |
| summary | string | ✅ | 单行可读摘要，按「参数错误 / 连接失败→建议回落 Scapy / 其他」分类 |
| artifacts | dict | 条件 | `{lua_script: path, lua_preview: 前200字符}` |
| response | string | live 且成功 | 硬件响应 |
| replaced_mac | list | 条件（G5 新增） | `[{index, from, to}]`，eth_dst_addr 替换明细 |
| rtt_during / attack_window / observation_window | dict | 带 dst_ip 时 | RTT 观测（见实体 5） |

**错误分类规则**: 含 "Connection" → 建议回落 Scapy；含 CompileError 或参数错误 → 参数错误提示；HITL 拒绝 → `HITL rejected by operator`。

## 实体 5：RTT 观测（RTT Observation）

| 字段 | 说明 |
|------|------|
| attack_window | `{start_ts, end_ts, mode}`；end=start+实际等待（封顶 60s） |
| observation_window | `{first_ts, last_ts, covers_attack_window}`；覆盖标志供 LLM 判定观测有效性 |
| rtt_during | 窗口内逐样本 RTT 与聚合统计（均值/最大/丢包等） |

ping 监控未启动时：字段以空值呈现、covers_attack_window=false（FR-011）。

## 实体 6：拓扑配置（Topology）

来源 `topology.yaml`（本特性不改动），读取失败回退内置默认。

| 字段 | 默认回退 | 用途 |
|------|---------|------|
| pktgen.host | 10.99.80.222 | 实发目标主机（env `PKTGEN_HOST` 优先） |
| pktgen.port | 22022 | 实发控制端口（env `PKTGEN_PORT` 优先） |
| tx/rx/monitor/target portlist | "0"/"1"/"all"/"all" | 端口映射（编译期 `$topology.*` 解析） |
| dst_mac.portlist | f0:c4:78:4c:a5:55 | packet_sequence 自动填充的真实目标 MAC |

## 校验规则汇总（本特性可测试口径）

1. rate ∈ [0,100]（编译期）；越界 → CompileError（FR-008）。
2. duration ∈ {0} ∪ (0, 60000]（适配器，G1）；>60000 → 拒绝（FR-009）。
3. src_ip 仅允许省略；传入 → 拒绝（G3，FR-016）。
4. dst_ip：需 allowlist 的技能必须非空且过白名单（FR-005）；arp 提供时同样校验（G2）。
5. sequences 非法 JSON → 拒绝（FR-013）；合法条目 eth_dst_addr 缺失/空/全 0-1 模式 → 替换为 dst_mac 并记录 replaced_mac（FR-012/G5）。
6. 同步等待时长 = min(duration, 60000) ms，duration=0 不等待（FR-009/010）。
