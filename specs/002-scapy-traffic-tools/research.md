# 阶段 0 研究：Scapy 流量工具集

**特性**: `specs/002-scapy-traffic-tools/` | **日期**: 2026-11-19 | **输入**: 规格澄清项与关键技术选型

## 决策记录

> 格式：决策 / 理由 / 备选方案。前三条为规格 [需要澄清] 项的推荐默认（Lead 指定采纳）。

### D1（澄清 002-1）钳制结果标注「已钳制」并返回原请求值

**决策**: 发送结果在保留 `params`（钳制后实际生效值）的同时，新增 `requested_params`（原请求值）与 `clamped` 字段；`clamped` 列出发生钳制的字段名（空列表表示未钳制）。HITL 审批明细展示钳制后的实际参数（现状不变）。

**理由**: Agent 需要明确知道自己请求超限，否则会误以为目标值已生效而继续加大，浪费轮次。结构化标注（而非文案）便于模型与测试程序直接判断；审批展示仍用实际值，保证「操作员所见即所批」。

**备选方案**: A) 仅返回实际值（现状）——已论证其导致决策盲区（FR-004）；B) 用自然语言警告字符串——不可靠解析；C) 拒绝超限请求而非钳制——与规格「超限按上限执行」矛盾。均不采纳。

### D2（澄清 002-2）抖动参数纳入统一配置（experiment.json）

**决策**: `mixed_traffic_send` 增加 `iat_jitter_ms` 参数（int，默认从 env `ATK_IAT_JITTER_MS` 读取，钳制 0–20），替换当前固定的 ±20ms 抖动；`experiment.json` 的 `attack` 分组已有 `iat_jitter_ms` 键（当前值 0），作为该参数的配置落点；系统提示（system_prompt.j2）的混合工具参数表同步补充。

**理由**: 配置单一来源（宪法六）要求抖动口径统一可配置；两个发送工具的流量形态可比是混合/单协议对比实验的前提。默认值 0 与 experiment.json 现状一致，对既有行为影响最小。

**备选方案**: A) 保持固定 ±20ms（现状）——与 traffic_send 不可比（FR-014）；B) 彻底移除抖动——丧失规格功能。均不采纳。

### D3（澄清 002-3）发送中断（Ctrl-C）标注「未完整发送」

**决策**: 发送循环被中断时，结果新增 `completed: false` 与 `interrupt_reason: "keyboard_interrupt"`；`packets_sent`/`elapsed_s`/`effective_pps` 照常返回已发生部分；观测字段（rtt_during 等）照常附带。`completed` 缺省为 `true`。

**理由**: 闭环可靠性（宪法二/五）——截断的发送窗口不应被 Agent 当作完整攻击观测来下结论；标注使「未完整发送」可机器判断。

**备选方案**: A) 静默返回（现状）——观测语义污染（FR-008）；B) 把截断当作错误丢弃全部结果——损失已采集数据。均不采纳。

### D4 上限常量权威来源与 docstring 修复方式

**决策**: 上限常量以 `src/tools/traffic_send_tool.py` 的 `MAX_PPS=20000 / MAX_DURATION_S=20 / MAX_PACKET_SIZE=1024 / MAX_FLOW_COUNT=100 / MAX_IAT_JITTER_MS=20` 与 `mixed_traffic_tool.py` 的 `MAX_STREAMS=100 / MAX_JSON_LENGTH=10000` 为唯一权威；`src/agent/tools.py` 中陈旧 docstring（max pps=200、duration=10s、packet_size=512、flow_count=50）在实施阶段改写为常量对应值；契约文件中的数值同样以常量为准。这是宪法附加约束「文档真实性」的直接执行（FR-018）。

**备选方案**: 以 docstring 为准修改常量——与宪法/CLAUDE.md 权威事实冲突。不采纳。

### D5 发送通道降级顺序（实现约束，非契约项）

**决策**: 保持现状三级降级——高权限原生通道（IP_HDRINCL）→ 无特权 UDP 通道（每流一个 socket）→ Scapy `send()`；结果以 `send_mode` 枚举（raw / udp / scapy）暴露实际通道。契约只定义枚举与语义，不定义实现细节。

**理由**: 跨平台无特权运行是既有设计（宪法「跨平台」附加约束）；把通道信息暴露给模型有助于解释有效速率差异。

**备选方案**: 只保留 Scapy 单通道——性能退化且依赖特权；在契约中固定通道选择逻辑——泄漏实现细节。均不采纳。

### D6 危险模式扫描与协议白名单维持现状

**决策**: 保持现状的协议白名单（IP/TCP/UDP/ICMP/DNS/Raw + DNS 嵌套构造器）与禁止模式清单（eval/exec/import/os/subprocess/open 等）及「IP.dst 强制覆盖」。实施阶段仅补测试锁定，不扩充协议集合。

**理由**: 安全优先（宪法四）——扩大白名单或动态构造会引入注入面；现状已满足规格 FR-010/011/013。

**备选方案**: 动态注册协议——违背安全原则。不采纳。

## 其余技术选型（现状确认，无改动）

- **HITL 门控**: `traffic_send` / `mixed_traffic_send` 在 @tool 层 `interrupt()` 审批（消息 + 参数明细），拒绝返回 `{"success": false, "error": "HITL rejected by operator"}`；`ping_rtt` / `log_result` 无 HITL。保持现状。
- **默认参数注入**: env `ATK_DURATION_S / ATK_PPS / ATK_PACKET_SIZE / ATK_FLOW_COUNT / ATK_IAT_JITTER_MS` 在 @tool 层调用时读取，未注入回退内置默认。保持现状（G2 将其扩展至混合工具）。
- **allowlist 加载**: `src/config/allowlist.json` 缺失/损坏回退内置默认列表；列表为空拒绝一切目标。保持现状（008 规格管理内容）。
- **观测字段**: 发送结果由 `build_rtt_observation` 追加 `rtt_during / attack_window / observation_window`（003 规格定义结构）。本特性只约束「必须附带」。

## 跟进项（不在本特性范围）

- 混合规格的百分比按流加权随机（CDF）实现属实现细节，契约仅约束「大批量发送占比偏差 ≤5 个百分点」（SC-006）。
- `ping_rtt` 的跨语言 ping 输出解析增强（中文 Windows）由 003 规格的监控后端覆盖，本特性维持现状。
