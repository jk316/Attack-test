# 快速验证：PCAP 业务流量画像

**特性**: `specs/004-pcap-profile/` | **日期**: 2026-11-19

端到端可运行验证场景（不含完整实现代码；命令均在项目根执行）。

## 前置

1. 依赖就绪：`uv sync`（Scapy 可用）。
2. 样本文件：任意 PCAP/PCAPng，或按 CLAUDE.md 使用 `data/sample.pcapng`；无样本时用 Scapy 构造一个小抓包（UDP 多目标多端口 + 少量 TCP/ICMP）用于口径核对。
3. 配置（差距 G-003 实施后生效）：`src/config/experiment.json` 的 `"pcap_profile"` 节（`max_packets=50000`、`idle_timeout_s=30`）。

## 场景 1：生成画像并核对字段（对应 P1、SC-003/SC-004/SC-005）

```bash
uv run python -c "from src.agent.tools import pcap_profile; import json; print(json.dumps(pcap_profile.invoke({'pcap_path':'data/sample.pcapng'}), ensure_ascii=False, indent=2))"
```

**预期结果**:
- 七个字段齐全：`top_dst_ips/top_dst_ports`（降序、各 ≤10）、`packet_size_hist`（桶概率和 = 1）、`iat_ms_stats`（mean/p50/p90）、`flow_stats`（`approx_flow_count` + `timeout_s=30`）、`payload_len_stats`、`notes`。
- notes 含 `UDP-only traffic profile. IAT calculated per (dst_ip, dst_port) flow.`，并按文件内容追加被忽略的 TCP/ICMP 数量。
- 已知构造抓包下：IAT 与负载统计与手工计算一致（误差 ≤ 0.01 ms）、流数按 5 元组 + 30 s 断流正确（含同源不同源端口两条流不被合并——G-001 修正后）。

## 场景 2：采样上限与截断注明（对应 P2 前置、SC-002）

```bash
uv run python -c "from src.agent.tools import pcap_profile; r=pcap_profile.invoke({'pcap_path':'<超过上限的抓包>','count':1000}); print(r['notes'])"
```

**预期结果**: notes 含 `Limited to 1000 packets.`；包数不超过上限的文件不出现截断说明。

## 场景 3：画像反哺初始参数（对应 P2、澄清 004-1）

```bash
uv run python -c "
from src.tools.profile_to_params import profile_to_params   # G-004 实施后
p = {
  'top_dst_ports':[53,123], 'packet_size_hist':{'64':0.2,'128':0.5,'256':0.3},
  'iat_ms_stats':{'mean':10.0,'p50':0,'p90':0}, 'flow_stats':{'approx_flow_count':8,'timeout_s':30}
}
print(profile_to_params(p))
"
```
另以 CLI 验证人工覆盖：`uv run python src/main.py --target-ip 10.99.80.160 --pcap-path data/sample.pcapng --pps 500 --max-iters 1 --auto-approve`——显式 `--pps 500` 应优先于映射值。

**预期结果**: 映射输出 `dst_port=53`、`packet_size=128`（中位数桶）、`flow_count=8`、`pps=100`（1000/10）、`duration_s=配置默认`；显式 CLI 参数覆盖映射值。

## 场景 4：异常稳健性（对应 P3、SC-006）

```bash
uv run python -c "from src.agent.tools import pcap_profile; print(pcap_profile.invoke({'pcap_path':'/no/such/file.pcap'})['notes'])"
uv run python -c "from src.agent.tools import pcap_profile; print(pcap_profile.invoke({'pcap_path':'/dev/null'})['notes'])"   # 空文件
```

**预期结果**: 返回字段完整结构（统计为空/零）、notes 分别注明「文件不存在」与「未发现 UDP 流量」，零异常。

## 场景 5：单元测试

```bash
uv run pytest tests/unit/test_pcap_profile_tool.py -v
```

**预期结果**: 全部通过；覆盖 UDP-only 隔离与忽略计数、IAT 分组与精度、5 元组流数（含 30 s 断流）、截断注明、异常输入批测与映射钳制（G-004 实施后）。
