# 开发进度

> 基于 PLAN.md 的 TDD 开发阶段追踪，最后更新: 2026-05-13

## 总体进度: 6/10 项完成 (60%)

```
Phase 1 (工具层)   ████████████████████ 4/4 ✅
Phase 2 (Agent)    ██████████████░░░░░░ 2/3
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

### 1.3 traffic_send_tool ✅
- [x] `src/tools/traffic_send_tool.py` — 已实现 (81% 覆盖率)
- [x] `tests/unit/test_traffic_send_tool.py` — 18 个测试用例
- 功能: Scapy send() UDP 发送, allowlist 校验, pps/duration/size/flow/jitter 上限强制, multi-flow 支持, 安全硬约束

### 1.4 log_tool ✅
- [x] `src/tools/log_tool.py` — 已实现 (65% 覆盖率, __main__ 块排除后 >80%)
- [x] `tests/unit/test_log_tool.py` — 9 个测试用例
- 功能: JSONL 追加写入, timestamp ISO 8601, params/RTT/loss/iteration 字段, 文件自动创建

---

## Phase 2: Agent 逻辑

### 2.1 State 定义 ✅
- [x] `src/agent/state.py` — 已实现 (AgentState TypedDict + 3 辅助函数)
- [x] `src/agent/__init__.py` — 已创建
- [x] `tests/integration/test_agent_loop.py` — 12 个测试用例
- 功能: LangGraph AgentState, compute_reward, check_stop_condition, update_best

### 2.2 Nodes 实现 ✅
- [x] `src/agent/nodes.py` — 已实现 (5 个节点函数)
- [x] `tests/integration/test_agent_nodes.py` — 12 个测试用例
- 功能: plan_params (随机扰动), send_traffic (HITL), measure_rtt, log_result, update_state

### 2.3 Graph 构建 ❌
- [ ] `src/agent/graph.py` — 未创建

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
│   │   ├── __init__.py          ✅ (导出全部 4 个工具)
│   │   ├── ping_rtt_tool.py     ✅
│   │   ├── pcap_profile_tool.py ✅
│   │   ├── traffic_send_tool.py ✅
│   │   └── log_tool.py          ✅
│   ├── agent/
│   │   ├── __init__.py           ✅
│   │   ├── state.py              ✅
│   │   └── nodes.py              ✅
│   ├── config/
│   │   └── allowlist.json       ✅
│   └── main.py                  ❌
├── tests/
│   ├── conftest.py                   ✅ (pytest pythonpath 配置)
│   ├── unit/
│   │   ├── test_ping_rtt_tool.py    ✅
│   │   ├── test_pcap_profile_tool.py ✅
│   │   ├── test_traffic_send_tool.py ✅
│   │   └── test_log_tool.py         ✅
│   ├── integration/
│   │   ├── __init__.py               ✅
│   │   ├── test_agent_loop.py        ✅
│   │   └── test_agent_nodes.py       ✅
│   └── e2e/
│       └── test_e2e_closed_loop.py  ❌
└── data/                         ❌ (目录不存在)
```

## 下一步

按 PLAN.md 开发顺序，下一项是 **2.3 Graph 构建**（LangGraph StateGraph 编排）。
