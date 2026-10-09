全部 **13 个** `cat_l2_*.py` 脚本均已写入并通过语法校验（dry-run，未执行、无流量）。达到 ≥10 的停止条件，现输出最终总结。

---

## 最终总结

### 攻击目录（L2 数据链路层）

| # | 攻击名称 | 类别 | 机制 | 脚本文件 | 关键参数 | 预期效果 |
|---|---------|------|------|---------|---------|---------|
| 1 | MAC 泛洪 / CAM 表溢出 | L2-交换机资源耗尽 | 海量随机源 MAC 撑爆交换机 MAC 地址表，退化为集线器行为 | `cat_l2_mac_flood.py` | tx_pps=80000, duration=30, mac_max=2^48-1 | CAM 表溢出、未知单播泛洪、可旁路嗅探 |
| 2 | ARP 欺骗 / 缓存投毒 | L2-中间人(MITM) | 伪造 ARP 应答把网关 IP 映射为攻击者 MAC，遍历投毒受害 IP | `cat_l2_arp_spoof.py` | tx_pps=2000, gateway_ip, victim 100~250 | ARP 表被篡改、流量被 MITM 劫持 |
| 3 | ARP 泛洪风暴 | L2-资源耗尽/DoS | 源/目的 IP+MAC 全随机的 ARP 请求狂刷，打满邻居表与 CPU | `cat_l2_arp_flood.py` | tx_pps=50000, ip 段 10.x.x.x | 邻居表耗尽、ARP 解析失败、丢包 |
| 4 | 免费 ARP 抢占 | L2-ARP 缓存污染 | psrc==pdst 的 GARP 广播宣称 IP-MAC，刷新全网缓存 | `cat_l2_gratuitous_arp.py` | tx_pps=10000, ip 10.0.0.1~10.0.255.255 | 全网 ARP 缓存抖动/污染、误转发、断网 |
| 5 | VLAN 跳跃(双层 802.1Q) | L2-二层隔离绕过 | 双层标签：外层 native，内层目标 VLAN，穿透 trunk 投递 | `cat_l2_vlan_hopping.py` | outer_vlan=1, inner 2~4094 | 跨 VLAN 投递、绕过二层隔离、触发 IDS |
| 6 | VLAN ID 暴力扫描 | L2-VLAN 枚举 | 单标签 VLAN 1~4094 遍历，探测可达/存在 VLAN | `cat_l2_vlan_sweep.py` | tx_pps=40000, vlan 1~4094 | 枚举二层分段、辅助隔离绕过 |
| 7 | STP BPDU 根桥劫持 | L2-拓扑操纵 | 伪造 802.3+LLC+SNAP+STP BPDU，桥优先级 0 抢根 | `cat_l2_stp_bpdu.py` | tx_pps=500, root_prio=0, 组播 01:80:c2:00:00:00 | 抢占根桥、拓扑重算震荡、流量牵引/断网 |
| 8 | DTP 中继协商攻击 | L2-私有协议操纵 | 伪造 DTP 帧(PID 0x2004)诱导端口协商为 trunk | `cat_l2_dtp_attack.py` | tx_pps=200, 组播 01:00:0c:cc:cc:cc | 端口变 trunk、全 VLAN 暴露 |
| 9 | CDP/LLDP 邻居泛洪 | L2-邻居表污染 | 海量 CDP(0x2000)/LLDP(0x88CC)邻居发现报文污染拓扑库 | `cat_l2_lldp_cdp_flood.py` | tx_pps=10000, 双流并发 | 邻居表膨胀、控制面 CPU 高占用 |
| 10 | 广播风暴 | L2-泛洪/带宽耗尽 | 全广播帧 + 随机源 MAC 高速洪泛，交换机全端口复制 | `cat_l2_broadcast_storm.py` | tx_pps=120000, dst=ff:ff:ff:ff:ff:ff | 广播域带宽耗尽、终端中断风暴 |
| 11 | 畸形帧/超长帧/EtherType 模糊 | L2-协议模糊测试 | 随机 EtherType + 随机帧长，迫使异常解析/慢路径 | `cat_l2_malformed_frame.py` | tx_pps=20000, etype 0~0xFFFF, size 60~1518 | 设备慢路径、丢包、可能触发 IDS |
| 12 | 802.1Q 优先级(CoS)滥用 | L2-QoS 队列操纵 | 随机/最高优先级 TCI 标签抢占高优先级队列 | `cat_l2_dot1q_priority.py` | tx_pps=60000, tci 0~0xFFFF | 高优先级队列被占、QoS 差分服务破坏 |
| 13 | MAC 冒充/MAC 表翻动 | L2-身份冒充 | 固定冒充源 MAC + 随机源 IP，反复更新转发表出端口 | `cat_l2_mac_spoof.py` | tx_pps=40000, spoof_src_mac | MAC 表翻动、被冒充主机断流、流量牵引 |

---

### 能力边界总结

**本次覆盖的攻击维度（L2 数据链路层为主）**
- **转发表/学习机制攻击**：MAC 泛洪(#1)、MAC 冒充/翻动(#13)——针对交换机 MAC 学习与转发平面。
- **ARP 协议攻击**：ARP 欺骗 MITM(#2)、ARP 泛洪(#3)、免费 ARP 抢占(#4)——覆盖欺骗、耗尽、污染三种子型。
- **VLAN/标签攻击**：双层标签跳跃(#5)、VLAN 枚举(#6)、802.1Q 优先级滥用(#12)——覆盖隔离绕过与 QoS 操纵。
- **链路协商/生成树控制协议攻击**：STP 抢根(#7)、DTP 中继协商(#8)、CDP/LLDP 邻居泛洪(#9)——针对 L2 控制平面协议。
- **泛洪与畸形帧**：广播风暴(#10)、EtherType 模糊 + 变长帧畸形(#11)——带宽耗尽与解析器 fuzz。

**TRex 表达这些攻击的主要技术手段**
- **STL 字段工程**：用 Scapy 逐层构造 `Ether/Dot1Q/ARP/Dot3/LLC/STP/Raw`，精确落到以太网、VLAN TCI、ARP 各字段偏移（如 Ether.src=6、Dot1Q TCI=14、ARP 起始=14）。
- **STL VM(变量修饰器)**：`STLVmFlowVar`(random/inc) + `STLVmWrFlowVar`(按 `pkt_offset` 改写字段) 实现 MAC/IP/VLAN/TCI/EtherType 的随机化与遍历；用同一 flow-var 写两处偏移实现"免费 ARP"(psrc==pdst)。
- **`STLVmTrimPktSize`**：随机裁剪帧长，制造短帧/超长帧。
- **多流组合**：`add_streams([s1,s2])` 并发下发（如 CDP+LLDP 混合泛洪）。
- **原始字节构造**：对 Scapy 无原生支持的私有协议（DTP/CDP），用 `Ether(...)/Raw(load=bytes.fromhex(...))` 手工拼装 LLC+SNAP+TLV。
- **速率/时长控制**：`STLTXCont(pps=...)` 连续流 + `c.start(duration=...)` + `wait_on_traffic` 做时长保护。

**未覆盖/可扩展的维度**
- **L2 加密/认证类协议**：802.1X/EAPoL 认证前攻击、MACsec、端口安全绕过未涉及。
- **L2 隧道/伪线**：VPLS、PBB(802.1ah)、GRE/以太网 over MPLS 未覆盖。
- **IPv6 邻居发现 (NDP) 攻击**：NS/NA 欺骗、RA 泛洪属 L2/L3 交界，本次未纳入。
- **时间同步/发现协议**：PTP(1588)、LLDP-MED、EtherCAT 等工业/时钟协议未覆盖。
- **流量行为维度**：本批为"单点手法 + 高pps 泛洪"为主，未做低速慢速自适应、多阶段组合攻击链（如先 DTP 协商 #8 → 再 VLAN 跳跃 #5 → 再 ARP 欺骗 #2 的级联）。
- **有状态侧**：全部基于 STL（无状态）；ASTF 状态机层面的 L2 交互（如真实 DTP/STP 会话握手）未使用。

**结论**：TRex 的 STL API 通过"Scapy 逐层构造 + VM 字段随机化/遍历 + 多流组合 + 原始字节拼装私有协议"四大手段，足以表达从**转发平面耗尽、ARP 欺骗、VLAN 绕过到控制协议操纵**的完整 L2 攻击谱系；其能力边界主要受限于对**有状态握手协议真实建模**（需 ASTF）与**加密/认证协议**（需真实凭据或证书）这两个方向。

探索完成，共生成并校验 **13 个** `cat_l2_*.py` 攻击脚本。