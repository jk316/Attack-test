全部 **15 个** `cat_*.py` 脚本写入且语法校验通过（dry-run，未发送任何流量）。最终总结如下。

---

# TRex 攻击能力探索 — 最终总结

| # | 攻击名称 | 类别 | 机制 | 脚本文件 | 关键参数 | 预期效果 |
|---|---------|------|------|---------|---------|---------|
| 1 | 多源多包 UDP 泛洪 | 流量型 DoS | 小源池（64 IP）持续发送定长 UDP，源 IP/端口双轮转，每源复用上千包 | `cat_udp_flood_multi_src.py` | SRC 池 64、PKT_SIZE=1024、PPS=20000、DURATION=30 | PPS/带宽打满、RTT 升高、软中断飙升 |
| 2 | SYN 泛洪 + 重传 | 半连接耗尽 | 双流共用同一小源池（首包流+重传流），每源 ≥2 个 SYN 进入 SYN_RECV | `cat_syn_flood_retrans.py` | BURST_PPS=12000、RETRANS_PPS=4000、DST_PORT=80 | 半连接队列占满、新连接失败 |
| 3 | ICMP 泛洪 + 分片变体 | 流量型/分片 | Echo 泛洪流 + 两片式 IP 分片流（MF=1/offset=175）共用源池 | `cat_icmp_flood_frag.py` | ECHO_PPS=10000、FRAG_PPS=5000、PAYLOAD=2000 | ICMP 路径与重组缓存占满、ping 丢包 |
| 4 | UDP 大包重叠分片（Teardrop 风格） | 分片重组 | 首片 offset=0 与尾片 offset=100 故意重叠，诱发重组异常 | `cat_udp_frag_teardrop.py` | OVERLAP_OFF=100、PPS=8000、PAYLOAD=2000 | ipfrag 队列耗尽、内核分片异常 |
| 5 | DNS 反射放大 | DRDoS | 伪造受害者源，向解析器池发长 qname 的 ANY 查询放大回注 | `cat_dns_amplify.py` | QNAME_LEN=60、PPS=8000、解析器池 10.99.80.100-110 | 受害者被放大应答淹没、DNS 超时 |
| 6 | NTP monlist + memcached 反射 | DRDoS | 单脚本并发两种高放大比反射（NTP/123 与 memcached/11211） | `cat_ntp_memcached_amplify.py` | NTP_PPS=3000、MEM_PPS=3000 | 超高放大比应答洪水、带宽耗尽 |
| 7 | HTTP GET 泛洪 | 应用层 DoS | ASTF 高 CPS 建连并发真实 HTTP GET，客户端/服务端 IP 池轮转 | `cat_http_get_flood_astf.py` | CPS=5000、CLIENT/SERVER 池各 100 | Web 服务连接/请求队列打满、5xx |
| 8 | Slowloris 慢速 HTTP | 慢速 DoS | ASTF 程序化 flow：分片发头不结束 + 周期补发，长连接占槽 | `cat_slowloris_astf.py` | CPS=500、HOLD_SEC=30 | 连接槽/工作线程耗尽、新连接受阻 |
| 9 | TCP 连接耗尽泛洪 | 状态耗尽 | ASTF 极高 CPS 短连接冲击 conntrack/backlog | `cat_tcp_conn_flood_astf.py` | CPS=20000、短连接程序 | CONNTRACK 溢出、新建连接失败 |
| 10 | TCP ACK 泛洪 | 状态耗尽 | 无握手 ACK，随机 seq，迫设备建会话表 | `cat_ack_flood.py` | PPS=20000、seq=random、DST_PORT=80 | 会话表满、新会话无法建立 |
| 11 | LAND 自环攻击 | 畸形报文 | src=dst、sport=dport，回包自环放大 | `cat_land_attack.py` | 自环池 10.99.80.100-110、PPS=15000 | CPU 因自环回包飙升、协议栈异常 |
| 12 | TCP 畸形标志扫描 | 畸形报文 | 三流发 Xmas(FPU)/NULL/FIN 非法标志组合 | `cat_tcp_flag_scan.py` | FLAG_SETS=FPU/""/F、各 PPS=8000 | 异常路径+IDS 规则匹配被压满 |
| 13 | 多目的端口扫描泛洪 | 扫描型 | 小源池对 1-1024 端口 SYN 扫描，源/端口双轮转 | `cat_port_sweep_flood.py` | DPORT=1-1024、PPS=15000 | 端口被占用/半连接、扫描告警 |
| 14 | TCP RST 泛洪（含反射） | 流量/重置 | 伪造源发 RST+随机 seq，直接洪泛并强制重置会话 | `cat_rst_flood.py` | PPS=20000、seq=random | 连接被异常重置、处理开销上升 |
| 15 | SYN-ACK 反射 | 反射型 | 伪造受害者源发 SYN-ACK，触发反射器回 RST/ACK | `cat_synack_reflection.py` | PPS=18000、反射器池 100-110 | 受害者被 RST/ACK 反射淹没、半开表耗尽 |

---

## 能力边界总结

### 1. 本次覆盖的攻击维度
- **协议层次**：L3（ICMP、IP 分片）、L4（UDP/TCP 各种标志与畸形组合）、L7（HTTP GET、Slowloris）
- **攻击范式**：带宽/PPS 泛洪、半连接与状态表耗尽、分片重组攻击、反射/放大（DRDoS）、应用层泛洪、慢速攻击、扫描探测、畸形报文
- **API 维度**：无状态 **STL**（字段工程、VM 变量机、多流组合）与有状态 **ASTF**（TCP 状态机、CPS 控制、程序化 flow）双覆盖
- **源地址策略**：所有脚本均落实到探索方向——**小源 IP 池 + 循环复用**，保证每个源 IP 出现 ≥2 次；SYN 类额外用**双流回填重传**，专门对抗「新源首包丢弃」

### 2. 对指定方向（每源多次 + 首包丢弃）的落地方式
| 手段 | 说明 | 涉及脚本 |
|------|------|---------|
| 小源池循环 | `STLVmFlowVar(op="inc")` 覆盖仅 64 个地址，连续模式下每源被复用数百~上千次 | 1,3,4,5,6,10,11,12,13,14 |
| 双流共用源池 | 首包流 + 重传流，确保每源 ≥2 包被放行 | 2 |
| 同变量写双字段 | 单变量同时写 `IP.src`/`IP.dst` 保证 LAND 语义下每源多次 | 11 |
| 源池+反射器池双轮转 | 伪造源重复出现以稳定接收放大应答 | 5,15 |

### 3. 未覆盖 / 受限的维度
- **需真实会话维持的攻击**：Slowloris 之外的更细慢速变体（RUDY、慢速读）仅给出一类
- **协议专属放大**：SSDP、Chargen、LDAP、SNMP 等更多反射向量未逐一展开
- **加密/隧道型**：TLS 握手耗尽（需要真实证书/库）、DNS over HTTPS 泛洪未涉及
- **L2 攻击**：ARP 欺骗/泛洪、MAC 泛洪、VLAN 跳跃——STL 虽可发 L2 帧，但需拓扑与镜像支持，本次未做
- **协议状态机漏洞利用**：如 TCP 会话劫持、SACK 崩溃等依赖实现细节的攻击
- **速率/分布自适应**：所有脚本为固定 PPS 恒定速率，未实现基于反馈的自适应攻击

### 4. TRex 表达攻击的主要技术手段
- **STL 字段工程**：`STLVmFlowVar`（inc/random）驱动 `IP.src/ip.dst/TCP.sport/dport/seq` 逐包变化；`STLVmWrFlowVar` 写入偏移；`STLVmFixIpv4` 修正 IP 校验和
- **多流组合**：用多条 `STLStream` 叠加不同标志/协议/速率，实现"同源多包""分片对""多向量并发"
- **STLTXCont 连续模式**：本身就是"每源多次"的天然载体——源池越小复用越频繁，直接命中探索方向
- **ASTF 状态机**：`ASTFProgram`（send/delay/recv）+ `ASTFTemplate(cps=...)` 表达真实 TCP 状态与连接级攻击；`ASTFIPGen(Dist)` 用 `seq` 分布让客户端 IP 重复建连
- **速率/规模控制**：`pps`、`cps` 与 TRex 乘数 `-m` 决定攻击强度

### 5. 结论
本次在 dry-run 模式下共构思并生成 **15 类攻击脚本**（远超 ≥10 的门槛），覆盖从 L3/L4 泛洪、状态耗尽、分片攻击、反射放大到 L7 应用层与慢速攻击的完整谱系；并针对用户指定方向统一实现了「**每个源 IP 出现多次**」的工程模式，用于对抗「**新源首包丢弃**」防御。TRex 的能力边界主要体现在：**无状态 STL 擅长海量字段可变的高速泛洪，有状态 ASTF 擅长真实协议状态机攻击**；受限于沙箱与拓扑，L2 攻击、需真实加密库的 TLS 攻击、以及自适应/反馈式攻击未纳入本次范围。