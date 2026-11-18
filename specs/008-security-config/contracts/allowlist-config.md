# 契约：allowlist.json 配置（目标白名单唯一管理源）

**特性目录**: `specs/008-security-config/` | **日期**: 2026-11-19 | **对应 FR**: FR-001/FR-002/FR-003

## 定位

`src/config/allowlist.json` 是允许目标 IP 的**唯一管理源**（宪法六）。任何流量工具、ping 工具、TRex 目标参数均通过 `validate_target()` 消费本文件；项目内不得出现第二份白名单定义（代码内 fallback 列表仅作「文件缺失时的默认候选」，语义上仍受失败关闭约束）。

## JSON Schema

```json
{
  "hosts": [
    "10.99.80.160",
    "100.1.11.4",
    "100.1.11.20",
    "100.1.11.3",
    "100.1.11.22"
  ]
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| hosts | string[] | 是 | 合法 IPv4 列表；重复项去重（无副作用）；顺序无语义 |

## 校验与失败关闭规则

1. **加载**: 进程启动（模块导入）时读取一次；运行期修改需重启进程生效。
2. **失败关闭（fail-closed）**:
   - 文件缺失 → 回退内置默认候选，但校验语义不变；
   - 文件存在但解析失败（JSON 损坏）→ 回退默认候选；
   - `hosts` 为空数组或缺失 → `validate_target` 对任何目标抛 "allowlist is empty"（零流量可发，SC-006）。
3. **条目合法性建议**: 条目应为合法 IPv4；广播（.255 结尾）与组播（224.0.0.0/4）条目永远无法通过 `validate_target`，不建议写入。
4. **非法格式条目**: 不影响其他条目；该条目永远不会匹配任何目标（`is_allowlisted` 为字符串精确匹配）。

## 消费者契约（validate_target 语义）

```text
validate_target(ip):
  1. allowlist 为空        → ValueError("allowlist is empty")
  2. ip 非合法 IPv4        → ValueError("Invalid IP format")
  3. ip 以 .255 结尾（广播） → ValueError("Broadcast address not allowed")
  4. ip 首段 ∈ [224,239]（组播）→ ValueError("Multicast address not allowed")
  5. ip ∉ hosts           → ValueError("Target … not in allowlist")
```

顺序固定：白名单非空 → 格式 → 广播 → 组播 → 归属。任一步失败即拒绝，调用方不得发包。

## 豁免项（门控矩阵，非本文件字段）

| 入口 | allowlist | 说明 |
|------|:---:|------|
| Pktgen arp_flood | 豁免 | L2 无 IP（dst_ip 仅用于 RTT 采样时仍须过白名单） |
| Pktgen pcap_replay | 豁免 | 使用 PCAP 自带目标；系统提示必须警告该豁免风险 |
| stats_monitoring / safe_stop_and_reset | N/A | 无流量 |

豁免由代码门控矩阵定义（adapter._SKILLS_WITH_DST_IP），不通过本文件表达——本文件只有「哪些 IP 被允许」，没有「哪些工具被豁免」。

## 治理

- 修改本文件属于授权操作（对应 README「使用本项目即表示你已获得目标环境的合法授权」声明）；新增条目需人工评审。
- 测试约定：10.99.80.160 用于放行断言、192.168.1.99 用于拒绝断言（tests 已约定）。
