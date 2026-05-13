# 闭环网络实验智能体 - 开发计划

## 1. 项目概述

**项目名称**: Closed-Loop Network Experiment Agent (闭环网络实验智能体)
**目标**: 在严格安全约束下，自动探索流量参数，基于 ping RTT 观测，最大化 RTT 指标
**技术栈**: Python 3.11+, LangChain + LangGraph, Scapy, UV

## 2. 核心架构

```
┌─────────────────────────────────────────────────────────────┐
│                    LangGraph Agent                          │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐ │
│  │ Plan    │───▶│ Send    │───▶│ Measure │───▶│ Log     │ │
│  │ Action  │    │ Traffic │    │ RTT     │    │ Result  │ │
│  └─────────┘    └─────────┘    └─────────┘    └─────────┘ │
│       ▲                                               │     │
│       └─────────────────────────────────────────────┘     │
│                     (Closed Loop)                          │
└─────────────────────────────────────────────────────────────┘
```

## 3. 安全约束设计

| 约束类型 | 实现方式 |
|---------|---------|
| allowlist | JSON 配置文件，只允许指定 IP:PORT |
| 速率限制 | pps <= 200, duration <= 10s |
| HITL 审批 | 人工确认环节 before sending |
| 禁止广播 | 校验 dst_ip 非 multicast/broadcast |
| 禁止伪造 | 不支持 src_ip 伪造 |

## 4. TDD 开发阶段

### Phase 1: 工具层 (Tools)

#### 1.1 ping_rtt_tool
```
RED: test_ping_rtt_tool.py
- 测试 allowlist 校验
- 测试输出格式 (JSON with avg_rtt_ms, loss_pct)
- 测试非 allowlist 拒绝
- 测试解析错误处理

GREEN: ping_rtt_tool.py
- 使用 subprocess 执行 ping
- 解析输出提取 RTT 和 loss
- 返回结构化 JSON
```

#### 1.2 pcap_profile_tool
```
RED: test_pcap_profile_tool.py
- 测试 Scapy rdpcap 读取
- 测试 count 限制 (N <= 50k)
- 测试输出字段完整性
- 测试 UDP-only 统计
- 测试 IAT 计算方式
- 测试 flow_count 近似

GREEN: pcap_profile_tool.py
- rdpcap() with count limit
- 按 (dst_ip, dst_port) 计算 IAT
- 按 5-tuple + 30s timeout 计算 flow
- 输出结构化 JSON
```

#### 1.3 traffic_send_tool
```
RED: test_traffic_send_tool.py
- 测试 allowlist 校验
- 测试参数上限 (pps<=200, duration<=10, packet_size<=512, flow_count<=50)
- 测试 iat_jitter_ms 抖动
- 测试安全硬约束 (无 broadcast/multicast, 无 src_ip 伪造)
- 测试输出格式

GREEN: traffic_send_tool.py
- Scapy send() L3 发送
- inter = 1/pps + jitter
- 最多 50 flows
- 严格参数校验
```

#### 1.4 log_tool
```
RED: test_log_tool.py
- 测试 JSONL 写入
- 测试追加模式
- 测试字段完整性

GREEN: log_tool.py
- 写入 JSONL 文件
- 包含 timestamp, params, rtt, loss
```

### Phase 2: Agent 逻辑 (Agent Loop)

#### 2.1 State 定义
```python
state = {
    "iteration": int,
    "traffic_params": dict,      # 当前参数
    "rtt_history": list,         # RTT 历史
    "loss_history": list,        # loss 历史
    "best_rtt": float,           # 最佳 RTT
    "consecutive_no_improve": int # 连续无提升轮次
}
```

#### 2.2 闭环逻辑 (TDD)
```
RED: test_agent_loop.py
- 测试参数探索策略
- 测试 reward = avg_rtt_ms - penalty(loss_pct)
- 测试停止条件 (max_iters=20, 连续5轮无提升)
- 测试 HITL 审批流程

GREEN: agent_loop.py
- 使用 LangGraph create_react_agent
- ReAct 方式调用 tools
- 实现参数探索策略
- 实现 HITL 审批节点
```

### Phase 3: 集成测试 (E2E)

```
RED: test_e2e_closed_loop.py
- 测试完整闭环流程
- 测试 allowlist 校验通过
- 测试流量发送与 RTT 测量
- 测试日志记录
- 测试停止条件触发

GREEN: 完整系统集成
```

## 5. 文件结构

```
attack-test/
├── pyproject.toml              # UV 依赖管理
├── src/
│   ├── __init__.py
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── ping_rtt_tool.py
│   │   ├── pcap_profile_tool.py
│   │   ├── traffic_send_tool.py
│   │   └── log_tool.py
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── state.py
│   │   ├── nodes.py          # LangGraph nodes
│   │   └── graph.py          # LangGraph 构建
│   ├── config/
│   │   ├── __init__.py
│   │   └── allowlist.json
│   └── main.py
├── tests/
│   ├── unit/
│   │   ├── test_ping_rtt_tool.py
│   │   ├── test_pcap_profile_tool.py
│   │   ├── test_traffic_send_tool.py
│   │   └── test_log_tool.py
│   ├── integration/
│   │   └── test_agent_loop.py
│   └── e2e/
│       └── test_e2e_closed_loop.py
└── data/
    └── .gitkeep
```

## 6. 依赖配置 (pyproject.toml)

```toml
[project]
requires-python = ">=3.11"
dependencies = [
    "langchain>=0.3.0",
    "langgraph>=0.2.0",
    "scapy>=2.6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov>=4.0",
    "pytest-asyncio>=0.23",
]
```

## 7. 关键参数上限

| 参数 | 上限 | 说明 |
|-----|------|-----|
| pps | 200 | 包每秒 |
| duration_s | 10 | 发送持续时间 |
| packet_size | 512 | payload 字节 |
| flow_count | 50 | 并发流数 |
| iat_jitter_ms | 20 | 抖动幅度 |
| max_packets | 50000 | pcap 采样上限 |
| max_iters | 20 | 最大迭代 |
| no_improve_limit | 5 | 连续无提升停止 |

## 8. HITL 审批设计

```python
def human_approval(traffic_params: dict) -> bool:
    """暂停等待人工确认"""
    print(f"[HITL] Proposed params: {traffic_params}")
    response = input("Approve? (y/n): ")
    return response.lower() == 'y'
```

## 9. 测试覆盖率目标

- 工具函数: 90%+
- Agent 逻辑: 85%+
- 集成测试: 覆盖完整流程

## 10. 开发顺序

```
Week 1: 工具层 (Tools)
├── ping_rtt_tool (TDD)
├── pcap_profile_tool (TDD)
├── traffic_send_tool (TDD)
└── log_tool (TDD)

Week 2: Agent 逻辑
├── state 定义
├── nodes 实现
├── graph 构建
└── HITL 集成

Week 3: 集成测试 & 优化
├── E2E 测试
├── 参数探索策略优化
└── 文档 & 清理
```

## 11. TDD 检查点 (Git Checkpoints)

每个阶段完成后创建 commit:
- `test: add ping_rtt_tool tests (RED)`
- `fix: implement ping_rtt_tool (GREEN)`
- `test: add pcap_profile_tool tests (RED)`
- `fix: implement pcap_profile_tool (GREEN)`
- `test: add traffic_send_tool tests (RED)`
- `fix: implement traffic_send_tool (GREEN)`
- `test: add agent_loop tests (RED)`
- `fix: implement agent_loop (GREEN)`
- `test: add e2e tests (RED)`
- `fix: complete e2e integration (GREEN)`