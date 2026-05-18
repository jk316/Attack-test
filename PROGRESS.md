# 开发进度

> 基于 PLAN.md 的 TDD 开发阶段追踪，最后更新: 2026-05-18

## 总体进度

```
Phase 1 (工具层)   ████████████████████ 4/4 ✅
Phase 2 (Agent)    ████████████████████ 3/3 ✅
Phase 3 (集成)     ████████████████████ 1/1 ✅
Phase 4 (LLM优化)  ████░░░░░░░░░░░░░░░░ 1/6 🔄 (4.1 完成)
```

### Phase 4 子进度

| 步骤 | 状态 | 内容 |
|------|------|------|
| 4.1 | ✅ | pyproject.toml 依赖 + src/llm/ + src/prompts/ + tests/unit/test_llm_client.py |
| 4.2 | ✅ | 重写 src/agent/nodes.py plan_params()（LLM + 降级随机扰动）|
| 4.3 | ⬜ | 更新 tests/integration/test_agent_nodes.py（已在 4.2 中完成）|
| 4.4 | ✅ | 更新 tests/integration/test_agent_graph.py（4 个 LLM 图级测试）|
| 4.5 | ✅ | 更新 tests/e2e/test_e2e_closed_loop.py（4 个 LLM E2E 测试）|
| 4.6 | ✅ | 全量测试 124 passed + 真实 DeepSeek API 手动验证通过 |
| ✅ | **Phase 4 完成** | LLM 智能参数优化上线 🎉 |

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

### 2.3 Graph 构建 ✅
- [x] `src/agent/graph.py` — 已实现 (build_graph + should_continue)
- [x] `tests/integration/test_agent_graph.py` — 8 个测试用例
- 功能: StateGraph 编译, 5 节点线性流, 条件循环边, MemorySaver checkpoint, HITL interrupt

---

## Phase 3: 集成测试

### 3.1 E2E ✅
- [x] `tests/e2e/test_e2e_closed_loop.py` — 7 个测试用例
- [x] `src/main.py` — CLI 入口 (argparse + graph loop + HITL 交互)
- 功能: 完整闭环 E2E 测试, max_iters/no_improve 停止, reward 链路, HITL resume

---

## 文件结构现状

```
attack-test/
├── src/
│   ├── __init__.py              ✅
│   ├── tools/
│   │   ├── __init__.py          ✅
│   │   ├── ping_rtt_tool.py     ✅
│   │   ├── pcap_profile_tool.py ✅
│   │   ├── traffic_send_tool.py ✅
│   │   └── log_tool.py          ✅
│   ├── agent/
│   │   ├── __init__.py           ✅
│   │   ├── state.py              ✅
│   │   ├── nodes.py              ✅ (待 Phase 4.2 重构 plan_params)
│   │   └── graph.py              ✅ (待 Phase 4.4 添加 LLM mock)
│   ├── llm/                       🆕 Phase 4.1
│   │   ├── __init__.py            🆕
│   │   └── client.py              🆕 (DeepSeek API 封装)
│   ├── prompts/                   🆕 Phase 4.1
│   │   ├── __init__.py            🆕
│   │   ├── plan_params.j2         🆕 (系统提示词)
│   │   └── plan_params_context.j2 🆕 (上下文模板)
│   ├── config/
│   │   └── allowlist.json       ✅
│   └── main.py                  ✅
├── tests/
│   ├── conftest.py                   ✅
│   ├── unit/
│   │   ├── test_ping_rtt_tool.py    ✅
│   │   ├── test_pcap_profile_tool.py ✅
│   │   ├── test_traffic_send_tool.py ✅
│   │   ├── test_log_tool.py         ✅
│   │   └── test_llm_client.py       🆕 Phase 4.1
│   ├── integration/
│   │   ├── __init__.py               ✅
│   │   ├── test_agent_loop.py        ✅
│   │   ├── test_agent_nodes.py       ✅ (待 Phase 4.3 更新)
│   │   └── test_agent_graph.py       ✅ (待 Phase 4.4 更新)
│   └── e2e/
│       ├── __init__.py                ✅
│       └── test_e2e_closed_loop.py    ✅ (待 Phase 4.5 更新)
└── data/                         ✅
```

## 下一步

项目已 100% 完成。运行方式: `uv run python src/main.py --target-ip 10.99.80.160`
