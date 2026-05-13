你是资深 Python 网络工程 + LangChain/LangGraph 工程师。请生成一个“闭环网络实验智能体”demo（仅用于本机或完全授权测试环境），目标是：在严格的安全约束下，自动探索一组“流量参数”，基于 ping RTT 观测，使 RTT 指标尽可能变大。必须实现allowlist、速率限制、HITL 人工审批

技术栈要求：
- Python 3.11+
- langchain + langgraph（使用 create_react_agent / tool-calling ReAct 方式构建闭环 agent）
- 工具（tools）必须包含：
  1) ping_rtt_tool：对 allowlist 目标执行 ping，解析输出得到 avg RTT（ms）与 loss%，返回结构化 JSON。
  2) pcap_profile_tool：读取 pcap/pcapng 文件，输出“业务流量画像 profile（结构化 JSON）”
   - 实现：优先使用 Scapy 的 rdpcap() 读取 PCAP（可设置 count 限制最多读取 N 包以避免内存爆炸）
   - 输出字段（至少包含）：
     {
       "top_dst_ips": [...],
       "top_dst_ports": [...],
       "packet_size_hist": { "64":0.2, "128":0.5, "256":0.3 },   # 归一化概率或计数
       "iat_ms_stats": { "mean":..., "p50":..., "p90":... },
       "flow_stats": { "approx_flow_count":..., "timeout_s":30 },
       "payload_len_stats": { "mean":..., "p50":..., "p90":... },
       "notes": "任何无法解析的情况要写明"
     }
   - 统计口径：
     - 仅统计 UDP（如果 pcap 里有 TCP/ICMP 先忽略）
     - IAT：按同一 (dst_ip,dst_port) 或同一 flow 计算相邻包 time delta（选择一种并写清楚）
     - flow_count：按 (src_ip,src_port,dst_ip,dst_port,proto) + idle timeout(默认30s) 近似
   - 约束：
     - 若 pcap 太大，必须支持只采样前 N 包（例如 N=50k）

  3) traffic_send_tool：仅对 allowlist 目标发送“合规的、低速率的、可控的”UDP 流量。实现方式使用 Scapy 组包与发送（优先 send() 三层发送；如需二层控制可选 sendp() 并显式指定 iface 与 Ether 头）。

     - 输入参数：
       - dst_ip, dst_port
       - duration_s (<=10)
       - pps (<=200)：通过 inter≈1/pps 控制发送间隔（允许 iat_jitter_ms 抖动）
       - packet_size (<=512)：通过 Raw(load=...) 控制 payload 长度
       - flow_count (<=50)：通过为每个 flow 分配不同 UDP(sport=...) 实现（默认不支持伪造 src_ip）
       - iat_jitter_ms (<=20)：每次发送前对 inter 做随机扰动（ms 级）

     - Scapy 可控字段（在代码中明确白名单）：
       - L3: IP(dst=...), 可选 IP(ttl/tos/id/flags) 但默认关闭
       - L4: UDP(dport=..., sport=...)
       - Payload: Raw(load=bytes) 控制包长
       - 发送控制: iface(可选)

     - 输出：
       - 实际发送包数（按 flow/总计）
       - 实际耗时、估计有效 pps
       - 参数回显与错误信息（超限/非 allowlist 必须拒绝）

     - 安全硬约束：
       - allowlist 校验、上限强制、默认 verbose=False
  - 禁止 broadcast/multicast、禁止 src_ip 伪造、禁止 loop 无限发送
  1) log_tool：把每轮的参数、RTT、loss、时间戳写入本地jsonl。

闭环逻辑（agent loop）：
- 每轮：
  A. 读取上一轮结果（state）
  B. 产生下一组候选参数：{traffic_params}
  D. 发送流量 traffic_send_tool
  E. 运行 ping_rtt_tool 获取 avg_rtt_ms、loss_pct
  F. 记录日志 log_tool
  G. 根据 reward = avg_rtt_ms - penalty(loss_pct) 做下一轮调整
- 停止条件：达到 max_iters（默认 20）或 RTT 无提升连续 5 轮

使用UV进行依赖管理