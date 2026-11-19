# 契约：混合流量输入规格（traffic_spec_json）

**特性**: `specs/002-scapy-traffic-tools/` | **日期**: 2026-11-19 | **对应 FR**: FR-010 / FR-011 / FR-012 / FR-013

## 1. 顶层结构

```json
{
  "streams": [
    {
      "stream_id": "udp_small",
      "protocol_stack": ["IP", "UDP"],
      "fields": {
        "IP": {"ttl": 64},
        "UDP": {"dport": 8080}
      },
      "percentage": 60
    }
  ]
}
```

## 2. 字段规则

| 字段 | 规则 |
|------|------|
| `streams` | 数组，长度 1–100（MAX_STREAMS） |
| `stream_id` | 非空字符串，全规格唯一 |
| `protocol_stack` | 非空数组；元素仅限 `IP`、`TCP`、`UDP`、`ICMP`、`DNS`、`Raw`（白名单） |
| `fields` | 对象；键为协议名、值为对象；DNS 嵌套仅限 `qd`/`an`/`ns`/`ar`（dict 或 list[dict]） |
| `percentage` | 整数 1–100；可缺失；全体总和必须 100 |

## 3. 覆盖与补齐规则

| 规则 | 行为 |
|------|------|
| 目标覆盖 | `fields.IP.dst` 的任何值被忽略，实际发送目标 = 工具参数 `dst_ip`（FR-011） |
| 百分比补齐 | 缺失 `percentage` 的流由 `(100 − 显式之和) / 缺失数` 均分补齐，余数依次 +1；显式之和 ≥100 时拒绝（FR-012） |

## 4. 拒绝条件（任一命中即拒绝整个规格，返回具体原因）

- 文本长度 > 10000 字符（MAX_JSON_LENGTH）
- 非 JSON / `streams` 非数组
- 流数 <1 或 >100；重复 `stream_id`
- `protocol_stack` 为空或含白名单外协议
- `percentage` 非整数 / 不在 1–100 / 总和 ≠100 且无法补齐
- `fields` 值命中危险模式：`__import__`、`eval(`、`exec(`、`compile(`、`os.`、`subprocess`、`sys.`、`shutil`、`open(`、`file(`、`input(`、`__`（递归扫描键与值）

## 5. 状态说明

本契约描述目标态；现状已满足绝大多数规则，差异点：混合工具抖动参数化（002-2，见 plan.md G2）不改变本契约结构。本文件是规格校验实现的权威依据。
