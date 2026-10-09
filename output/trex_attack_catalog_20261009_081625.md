全部 26 个攻击脚本生成并校验通过（`syntax_ok=true`），无语法错误。以下为最终总结。

---

## 最终攻击目录总结

| # | 攻击名称 | 类别 | 机制 | 脚本文件 | 关键参数 | 预期效果 |
|---|---------|------|------|---------|---------|---------|
| 1 | ICMP Echo 洪泛 | L3/ICMP 洪泛 | 高 PPS ICMP type=8，源地址/标识随机，逼目标逐包回包 | `cat_icmp_flood.py` | `PPS=200000, PKT_SIZE=64, SRC_RANGE` | RTT↑、ICMP 队列溢出、CPU 软中断飙升 |
| 2 | 分片 ICMP 洪泛 | L3/ICMP 分片 | 超大 Ping 按 MF 分片发送，压垮重组缓冲 | `cat_icmp_frag_flood.py` | `PPS=100000, FRAG_SZ=1472` | 重组失败/超时激增、重组缓存耗尽 |
| 3 | 重叠分片 (Teardrop) | L3/畸形分片 | 偏移重叠分片制造重组歧义/长度冲突 | `cat_ip_frag_overlap.py` | `PPS=50000` | 重组模块异常、内核告警、丢包 |
| 4 | IP 选项滥用洪泛 | L3/IP 选项 | 40 字节 Timestamp 选项使头达 60B，逼走慢路径 | `cat_ip_options_abuse.py` | `PPS=150000, OPT_BYTES=40` | 转发吞吐↓、RTT↑、CPU↑ |
| 5 | 路由协议洪泛 | L3/路由协议 | OSPF Hello(组播)+伪 BGP OPEN 洪水 | `cat_routing_proto_flood.py` | `PPS=80000, OSPF_MCAST=224.0.0.5` | 路由进程 CPU 打满、邻接震荡 |
| 6 | 畸形 IP 头攻击 | L3/畸形报文 | 坏校验和/假长度/TTL=0/保留位 | `cat_l3_bad_header.py` | `PPS=120000` | 校验失败告警、处理路径被拖慢、IDS 告警 |
| 7 | TCP SYN 洪泛 | L4/TCP 洪泛 | 随机源 SYN 占满半连接表 | `cat_tcp_syn_flood.py` | `PPS=300000, DST_PORT=80` | SYN 队列耗尽、合法连接超时 |
| 8 | UDP 洪泛 | L4/UDP 洪泛 | 随机端口+负载 UDP 洪水 | `cat_udp_flood.py` | `PPS=400000, PAYLOAD_SZ=512` | 带宽饱和、UDP 队列丢包 |
| 9 | TCP ACK 洪泛 | L4/TCP 洪泛 | 随机 seq/ack 的 ACK 洪水 | `cat_tcp_ack_flood.py` | `PPS=300000` | 连接查找开销↑、CPU↑、带宽被占 |
| 10 | TCP RST 洪泛 | L4/TCP 洪泛 | 大量 RST 强行重置连接 | `cat_tcp_rst_flood.py` | `PPS=250000` | 连接被误重置、服务间歇中断 |
| 11 | 隐蔽端口扫描 | L4/扫描侦察 | XMAS/NULL/FIN 标志组合扫描端口 | `cat_tcp_scan_stealth.py` | `PORT_MIN/MAX, PPS=50000` | 扫描告警、暴露服务指纹 |
| 12 | 分片 UDP 洪泛 | L4/UDP 分片 | UDP 切分片发送(可重叠)，重组压力+分片逃避 | `cat_udp_frag_flood.py` | `PPS=80000, FRAG_SZ=1472` | 重组压力、UDP 延迟↑、IDS 漏检 |
| 13 | UDP 放大反射 | L4/反射放大 | 伪造受害者源向开放解析器发 DNS ANY | `cat_udp_amplification.py` | `REFLECTORS, PPS=20000` | 受害者被放大流量淹没、溯源困难 |
| 14 | SYN 反射攻击 | L4/反射放大 | 伪造源 SYN 触发海量 SYN-ACK 回击受害者 | `cat_tcp_syn_reflection.py` | `SERVERS, PPS=15000` | 受害者连接表/带宽被占 |
| 15 | 零窗口耗尽 (类 Sockstress) | L4/状态耗尽 | SYN(极小 MSS)+window=0 ACK 占用连接资源 | `cat_sockstress_window.py` | `MSS=48, PPS=60000` | 连接缓存/内存耗尽、建连变慢 |
| 16 | TCP 连接表耗尽 (ASTF) | L4/L7 有状态 | 真实握手+快速关闭的短连接风暴 | `cat_tcp_conn_exhaust.py` | `MULT=2000, DURATION=30` | 连接跟踪表/FD 耗尽、服务不可用 |
| 17 | HTTP GET 洪泛 | L7/HTTP | GET 请求洪水+随机 URI 破缓存 | `cat_http_get_flood.py` | `PPS=150000, URI_OFF=59` | Web CPU/线程打满、WAF 告警 |
| 18 | HTTP POST 洪泛 | L7/HTTP | 大 Body POST 洪水压后端写入 | `cat_http_post_flood.py` | `PPS=80000, BODY_SZ=1024` | 后端写入拖慢、内存/带宽↑ |
| 19 | Slowloris 慢速攻击 (ASTF) | L7/慢速 | 慢速分片发送不完整头并长连 | `cat_slowloris.py` | `MULT=800, DELAY_US=500000` | 线程池被慢连接占满、正常请求超时 |
| 20 | DNS 查询洪泛 | L7/DNS | 随机子域查询造成缓存穿透 | `cat_dns_query_flood.py` | `PPS=200000, SUBC_OFF=55` | 解析器递归资源耗尽、解析超时 |
| 21 | DNS NXDOMAIN 洪泛 | L7/DNS | 查询必然不存在域名迫走完整递归 | `cat_dns_nxdomain_flood.py` | `PPS=160000, LBL_OFF=55` | 解析器 CPU 打满、队列积压 |
| 22 | TLS 握手洪泛 | L7/TLS | 仅发 ClientHello 不完成握手耗密钥运算 | `cat_tls_handshake_flood.py` | `PPS=100000, DST_PORT=443` | CPU 因数论运算打满、握手超时 |
| 23 | SIP INVITE 洪泛 | L7/VoIP | UDP/5060 呼叫洪水建会话状态 | `cat_sip_invite_flood.py` | `PPS=80000, DST_PORT=5060` | 呼叫状态耗尽、合法呼叫失败 |
| 24 | HTTP 管道化滥用 | L7/协议滥用 | 单段串联多 GET 放大每包处理 | `cat_http_pipeline_abuse.py` | `REPEAT=16, PPS=60000` | 请求队列积压、后端连接池耗尽 |
| 25 | SNMP Get 洪泛 | L7/SNMP | UDP/161 SNMP GetRequest 洪水 | `cat_snmp_flood.py` | `PPS=100000, DST_PORT=161` | SNMP 代理 CPU 打满、管理查询超时 |
| 26 | 全端口多主机扫描 | L4/扫描侦察 | SYN 遍历 1-65535 端口扫描 | `cat_port_scan_sweep.py` | `PPS=40000, PORT_MAX=65535` | 采集服务清单、触发大规模扫描告警 |

---

## 能力边界总结

**1. 本次覆盖的攻击维度（L3–L7 全栈）**
- **L3 网络层（6 类）**：ICMP 洪泛、分片洪泛、重叠分片(Teardrop)、IP 选项滥用、路由协议(OSPF/BGP)洪泛、畸形 IP 头（坏校验和/假长度/TTL=0/保留位）。
- **L4 传输层（9 类）**：SYN/UDP/ACK/RST 四类洪泛、XMAS/NULL/FIN 隐蔽扫描、分片 UDP、UDP 放大反射(DNS)，SYN 反射、零窗口(Sockstress)状态耗尽。
- **有状态 L4/L7（1 类）**：ASTF 全握手短连接风暴，实现连接跟踪表耗尽。
- **L7 应用层（9 类）**：HTTP GET/POST 洪泛、Slowloris 慢速、DNS 查询/NXDOMAIN 洪泛、TLS 握手洪泛、SIP INVITE 洪泛、HTTP 管道化滥用、SNMP 洪泛。
- **手段维度**：洪泛(Flood)、放大反射(Amplification/Reflection)、协议畸形(Malformed)、分片/逃避(Fragmentation)、状态耗尽(资源耗尽)、慢速攻击(低速持续占用)、扫描侦察(Recon)、协议语义滥用 共 8 类攻击手段。

**2. TRex 表达这些攻击的主要技术手段**
- **STL 字段工程**：用 `STLVmFlowVar` + `STLVmWrFlowVar` 对 `IP.src` / `TCP.sport,seq` / `UDP.sport` 等字段做随机/递增注入，`STLVmFixIpv4` 修正校验和，支持整数型 `pkt_offset` 向原始负载（URI/子域/标签）写入随机值 —— 这是 L3/L4 洪泛与 DNS/HTTP 随机化攻击的核心。
- **原始报文构造**：通过 scapy 分层（`IP(flags='MF', frag=…)`、`IP(options=...)`）与 `Raw(load=...)` 手工拼装 OSPF/BGP/TLS/SIP/SNMP/DNS 协议载荷，实现协议畸形与握手类攻击。
- **多流组合**：单次 `add_streams` 挂载多条流（分片首/尾片、多反射器、多扫描标志、XMAS/NULL/FIN 三连）实现复合流量。
- **ASTF 状态机**：`ASTFProgram` 的 `connect/ssend/recv/delay/close` 序列可构建真实三次握手、慢速粘滞连接与短连接风暴，覆盖 STL 无法表达的有状态攻击（Slowloris、连接耗尽）。

**3. 未覆盖/受限维度（能力边界）**
- 真正的**应用层加密负载攻击**（如完整 TLS 会话内 HTTP/2 攻击、QUIC）：STL 只能造 ClientHello，无法完成 TLS 记录层握手后精细交互，需 ASTF 或外部栈配合。
- **真实协议漏洞利用**（如特定 CVE 的内存破坏）：属于畸形包范畴，但成功与否依赖目标实现，TRex 只能构造旁路/拒绝服务型流量。
- **反射器发现与动态源生成**：脚本用静态反射器/服务器列表与固定伪造源网段，未做开放解析器主动发现。
- **僵尸网络级分布式源 IP**：TRex 单机源地址为仿真范围（16.0.0.x），非跨自治域真实源，放大攻击的“欺骗真实性”受限。
- **应用层慢速攻击的精确连接保活**：STL 无状态无法长期维持单连接，Slowloris 只能靠 ASTF 近似。
- **可插拔字段级校验符**（TCP/UDP 校验和 VM）未显式使用，实际运行依赖网卡校验和 offload 配置。
- **加密/规避型 C2 与多阶段攻击链**：超出单次流量生成器能力范围。

**结论**：本次以 **26 个脚本、覆盖 L3→L7 全层级、8 类攻击手段**，验证了 TRex（STL 字段工程 + 原始报文构造 + 多流组合 + ASTF 状态机）作为攻击流量生成器的表达能力边界；核心优势在**高速、可编程的 L3/L4 洪泛、放大反射与 L7 协议洪泛**，边界主要在**加密会话内部的精细应用层交互与分布式真实源仿真**。所有脚本均处于 dry-run 状态，**未发送任何流量**。