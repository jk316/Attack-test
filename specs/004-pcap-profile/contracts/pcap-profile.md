# 契约：PCAP 画像 JSON 结构与反哺映射

**特性**: `specs/004-pcap-profile/` | **消费者**: Agent 工具层（`pcap_profile`）、初始参数映射（`profile_to_params`）、LLM 上下文 | **日期**: 2026-11-19

定义 `pcap_profile` 工具返回值的 JSON 形状，以及画像 → 初始流量参数的确定性映射契约（澄清 004-1 采纳）。字段名与语义是对既有实现的固化；实施不得破坏，新增字段须向后兼容（只增不改）。

## 1. 画像输出结构

```json
{
  "top_dst_ips": ["10.99.80.160", "10.99.80.161"],
  "top_dst_ports": [53, 123],
  "packet_size_hist": { "64": 0.2, "128": 0.5, "256": 0.3 },
  "iat_ms_stats": { "mean": 12.34, "p50": 10.0, "p90": 25.0 },
  "flow_stats": { "approx_flow_count": 8, "timeout_s": 30 },
  "payload_len_stats": { "mean": 512.0, "p50": 512.0, "p90": 1024.0 },
  "notes": "UDP-only traffic profile. IAT calculated per (dst_ip, dst_port) flow."
}
```

| 字段 | 类型 | 约束 |
|------|------|------|
| `top_dst_ips` | string[] | 目标 IP 按包数降序，≤10 个；无 UDP 时 `[]` |
| `top_dst_ports` | integer[] | 目标端口按包数降序，≤10 个；无 UDP 时 `[]` |
| `packet_size_hist` | object | 键 ∈ {`64`,`128`,`256`,`512`,`1024`,`other`}；值为归一化概率（0–1，四舍五入 4 位）；出现过的桶概率和为 1 |
| `iat_ms_stats` | `{mean,p50,p90}` | 毫秒；p50/p90 为百分位；无 IAT 时全 0 |
| `flow_stats` | `{approx_flow_count, timeout_s}` | 5 元组 + idle timeout 近似流数；`timeout_s` 为实际所用阈值（默认 30，可配置） |
| `payload_len_stats` | `{mean,p50,p90}` | UDP 负载字节数统计；无 UDP 时全 0 |
| `notes` | string（非空） | 见下「notes 内容契约」 |

### notes 内容契约

- 必含口径声明：`UDP-only traffic profile. IAT calculated per (dst_ip, dst_port) flow.`
- 条件性追加（与条件一一对应）：
  - 读取达上限：`Limited to N packets.`（N 为实际上限）
  - 有 TCP：`Ignored <n> TCP packets.`；有 ICMP：`Ignored <n> ICMP packets.`；有非 IP：`Ignored <n> non-IP packets.`
  - 无任何 UDP 包：必须显式注明未发现 UDP 流量（差距 G-002）
  - 文件不存在：`File not found: <path>`
  - 解析失败：`Error parsing pcap: <reason>`
  - 依赖缺失：`Scapy not available, cannot parse pcap`

**失败语义**: 上述异常场景返回字段完整结构（统计为空/零）+ 相应 notes，不得抛未捕获异常（FR-010）。

## 2. 反哺映射契约（profile → 初始参数）

输入画像（第 1 节结构），输出初始流量参数建议（`profile_to_params` 纯函数）。

| 输出参数 | 规则 | 钳制/回落 |
|---------|------|----------|
| `dst_port` | `top_dst_ports[0]` | 画像无 UDP 或排行空 → 回落配置默认端口；范围 1–65535 |
| `packet_size` | 直方图概率累计 ≥ 50% 的首个桶（中位数桶） | ≤ MAX_PACKET_SIZE(1024)；直方图为空 → 回落配置默认 |
| `flow_count` | `approx_flow_count` | clamp 到 [1, MAX_FLOW_COUNT=100] |
| `pps` | `1000 / iat_ms_stats.mean` | mean ≤ 0 或无 IAT → 回落配置默认；clamp 到 [1, MAX_PPS=20000] |
| `duration_s` | 维持配置默认（画像不约束时长） | ≤ MAX_DURATION_S(20) |

**优先级（人工覆盖）**: CLI 显式参数 > 映射值 > `experiment.json` 默认值。映射值仅作为「未显式指定」时的初始种子注入会话上下文。

**安全不变式**: 映射输出仅是流量工具的输入候选，流量工具内部仍执行 allowlist / 参数上限钳制 / HITL 三重门禁；本契约不提供任何绕过途径。

## 3. 映射示例

画像（截取）→ 参数建议:

```json
// 输入
{ "top_dst_ports": [53, 123], "packet_size_hist": { "64": 0.2, "128": 0.5, "256": 0.3 },
  "iat_ms_stats": { "mean": 10.0 }, "flow_stats": { "approx_flow_count": 8, "timeout_s": 30 } }

// 输出
{ "dst_port": 53, "packet_size": 128, "flow_count": 8, "pps": 100, "duration_s": 10 }
```
（`packet_size`: 概率累计 0.2 < 0.5，0.2+0.5 ≥ 0.5 → 桶 128；`pps = 1000/10 = 100`；`duration_s` 取配置默认 10。）

## 4. 语义约束（供实现与测试）

1. 口径隔离：TCP/ICMP/非 IP 不进入任何统计字段（FR-012）。
2. 流键严格 5 元组 `(src_ip, src_port, dst_ip, dst_port, protocol)`（差距 G-001 修正后的语义）。
3. IAT 按 `(dst_ip, dst_port)` 分组、组内按时间排序后取相邻差（FR-006）。
4. 截断注明与实际读取行为严格一致（读取达上限 ⇔ notes 含 `Limited to`）（SC-002）。
