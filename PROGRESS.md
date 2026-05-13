# 开发进度

> 基于 PLAN.md 的 TDD 开发阶段追踪，最后更新: 2026-05-13

## 总体进度: 2/10 项完成 (20%)

```
Phase 1 (工具层)   ████████░░░░░░░░░░░░ 2/4
Phase 2 (Agent)    ░░░░░░░░░░░░░░░░░░░░ 0/3
Phase 3 (集成)     ░░░░░░░░░░░░░░░░░░░░ 0/1
```

---

## Phase 1: 工具层 (Tools)

### 1.1 ping_rtt_tool ✅
- [x] `src/tools/ping_rtt_tool.py` — 已实现
- [x] `tests/unit/test_ping_rtt_tool.py` — 10 个测试用例
- 功能: allowlist 校验, ping 执行, RTT/loss 解析, 广播/多播拒绝

### 1.2 pcap_profile_tool ✅
- [x] `src/tools/pcap_profile_tool.py` — 已实现
- [x] `tests/unit/test_pcap_profile_tool.py` — 13 个测试用例
- 功能: Scapy rdpcap 读取, UDP-only 统计, IAT/flow/payload 分析, count 限制

### 1.3 traffic_send_tool ❌
- [ ] `src/tools/traffic_send_tool.py` — 未创建
- [ ] `tests/unit/test_traffic_send_tool.py` — 未创建
- 计划: Scapy send() UDP 发送, allowlist 校验, pps/duration/size 上限强制

### 1.4 log_tool ❌
- [ ] `src/tools/log_tool.py` — 未创建
- [ ] `tests/unit/test_log_tool.py` — 未创建
- 计划: JSONL 追加写入, 记录 params/RTT/loss/timestamp

---

## Phase 2: Agent 逻辑

### 2.1 State 定义 ❌
- [ ] `src/agent/state.py` — 未创建

### 2.2 Nodes 实现 ❌
- [ ] `src/agent/nodes.py` — 未创建

### 2.3 Graph 构建 ❌
- [ ] `src/agent/graph.py` — 未创建
- [ ] `tests/integration/test_agent_loop.py` — 未创建

---

## Phase 3: 集成测试

### 3.1 E2E ❌
- [ ] `tests/e2e/test_e2e_closed_loop.py` — 未创建
- [ ] `src/main.py` — 未创建

---

## 文件结构现状

```
attack-test/
├── src/
│   ├── __init__.py              ✅
│   ├── tools/
│   │   ├── __init__.py          ✅ (仅导出 ping_rtt_tool)
│   │   ├── ping_rtt_tool.py     ✅
│   │   ├── pcap_profile_tool.py ✅
│   │   ├── traffic_send_tool.py ❌
│   │   └── log_tool.py          ❌
│   ├── agent/                   ❌ (目录不存在)
│   ├── config/
│   │   └── allowlist.json       ✅
│   └── main.py                  ❌
├── tests/
│   ├── unit/
│   │   ├── test_ping_rtt_tool.py    ✅
│   │   ├── test_pcap_profile_tool.py ✅
│   │   ├── test_traffic_send_tool.py ❌
│   │   └── test_log_tool.py         ❌
│   ├── integration/
│   │   └── test_agent_loop.py       ❌
│   └── e2e/
│       └── test_e2e_closed_loop.py  ❌
└── data/                         ❌ (目录不存在)
```

## 下一步

按 PLAN.md 开发顺序，下一项是 **1.3 traffic_send_tool**（TDD: 先写测试再实现）。
