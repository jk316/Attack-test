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

### Phase 4: LLM 智能参数优化 (plan_params 重构)

当前 `plan_params` 使用随机扰动（每个参数 50% 概率 ±20%），不基于 RTT 反馈进行学习。Phase 4 将其替换为基于 DeepSeek API 的 LLM 智能决策。

#### 4.1 架构设计

```
plan_params 节点
├── 第 0 轮 → 返回 DEFAULT_PARAMS（不调用 LLM）
└── 第 1+ 轮 →
    ├── 1. 从 state 提取 RTT 历史、loss 历史、当前参数
    ├── 2. 用 Jinja2 渲染上下文提示词
    ├── 3. 调用 DeepSeek API（OpenAI 兼容接口）
    ├── 4. 解析 JSON 响应，提取新参数
    ├── 5. Clamp 所有值到安全边界内
    └── 失败时 → 降级为随机扰动（原逻辑）
```

#### 4.2 新增文件

| 文件 | 用途 |
|------|------|
| `src/llm/__init__.py` | 导出 LLMClient, LLMClientError |
| `src/llm/client.py` | DeepSeek API 客户端封装（OpenAI SDK） |
| `src/prompts/__init__.py` | 包初始化 |
| `src/prompts/plan_params.j2` | 系统提示词模板（含参数边界和优化策略） |
| `src/prompts/plan_params_context.j2` | 上下文提示词模板（含历史表格和当前状态） |
| `tests/unit/test_llm_client.py` | LLM 客户端单元测试 |

#### 4.3 修改文件

| 文件 | 变更内容 |
|------|---------|
| `pyproject.toml` | 添加 `openai>=1.0.0`, `jinja2>=3.0.0` 依赖 |
| `src/agent/nodes.py` | 重写 `plan_params()`，提取 `_random_perturbation()` 降级函数 |
| `tests/integration/test_agent_nodes.py` | 更新 TestPlanParams 测试，新增 LLM mock 场景 |
| `tests/integration/test_agent_graph.py` | 添加 `_get_llm_client` mock |
| `tests/e2e/test_e2e_closed_loop.py` | 多轮测试添加 LLM mock |

#### 4.4 LLM 客户端设计 (`src/llm/client.py`)

```python
class LLMClientError(Exception): ...

class LLMClient:
    def __init__(self, api_key=None, base_url="https://api.deepseek.com"):
        # 从环境变量.env中读取 DEEPSEEK_API_KEY 和 LLM_MODEL, 作为调用的模型 
        # 创建 openai.OpenAI 实例

    def chat(self, messages: list[dict]) -> dict:
        # 发送请求到 deepseek-chat 模型
        # 解析 JSON 响应（处理 ```json 代码块）
        # 返回解析后的 dict

    @staticmethod
    def _parse_json_response(content: str) -> dict:
        # 正则提取 JSON（兼容 markdown 代码块）
        # json.loads 解析
        # 失败抛出 LLMClientError
```

#### 4.5 提示词设计

**系统提示词** (`plan_params.j2`) — 模块加载时渲染一次：
- 角色定义："网络流量参数优化智能体"
- 参数边界注入（`{{ max_pps }}`, `{{ max_duration_s }}` 等，与代码常量同步）
- 优化策略指导：梯度跟随、探索/利用平衡、拥塞原理
- 严格的 JSON 输出格式要求

**上下文提示词** (`plan_params_context.j2`) — 每轮渲染：
- 当前迭代数 / 最大迭代数
- 最佳 RTT 和无改善计数
- 历史记录表格（最近 10 轮）：参数、RTT、loss%、reward
- 当前参数快照

LLM 返回的 JSON 格式：
```json
{
  "params": {
    "dst_port": 8080, "duration_s": 5, "pps": 50,
    "packet_size": 64, "flow_count": 1, "iat_jitter_ms": 5
  },
  "reasoning": "基于正向RTT趋势，继续增加pps和flow_count"
}
```

#### 4.6 错误处理策略

| 失败场景 | 处理方式 |
|---------|---------|
| `DEEPSEEK_API_KEY` 未设置 | `LLMClientError` → 降级为随机扰动 |
| API 网络超时/错误 | `LLMClientError` → 降级为随机扰动 |
| LLM 返回非 JSON | `_parse_json_response` 失败 → 降级 |
| JSON 缺少参数 key | 从上轮参数填充默认值 |
| 参数值超出边界 | `_clamp()` 强制限制 |
| 参数值非整数 | `int()` 转换，失败则用上轮值 |

#### 4.7 测试策略

1. **单元测试** (`tests/unit/test_llm_client.py`): 客户端初始化、JSON 解析（普通/fenced/非法）、chat 方法消息传递 — 全部 mock OpenAI SDK
2. **集成测试** (`tests/integration/test_agent_nodes.py`): 第0轮默认值、LLM 调用解析、边界clamp、失败降级、缺失key填充
3. **图测试** (`tests/integration/test_agent_graph.py`): 添加 LLM mock
4. **E2E 测试** (`tests/e2e/test_e2e_closed_loop.py`): 多轮测试添加 LLM mock

#### 4.8 实施步骤

```
1. pyproject.toml 添加 openai, jinja2 依赖，uv sync
2. 创建 src/llm/ 模块 (client.py)
3. 创建 src/prompts/ 模板文件夹 (plan_params.j2, plan_params_context.j2)
4. 创建 tests/unit/test_llm_client.py
5. 重写 src/agent/nodes.py 的 plan_params()
6. 更新 tests/integration/test_agent_nodes.py
7. 更新 tests/integration/test_agent_graph.py
8. 更新 tests/e2e/test_e2e_closed_loop.py
9. 运行全量测试，确认无回归
10. 手动验证: DEEPSEEK_API_KEY=xxx uv run python src/main.py --max-iters 5
```

#### 4.9 验证标准

- [ ] `uv run pytest tests/unit/ -v` 全部通过
- [ ] `uv run pytest tests/integration/ -v` 全部通过
- [ ] `uv run pytest tests/e2e/ -v` 全部通过
- [ ] `uv run pytest --cov=src --cov-report=term-missing` 覆盖率 ≥ 80%
- [ ] 手动端到端测试：带 `DEEPSEEK_API_KEY` 运行完整闭环

---

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