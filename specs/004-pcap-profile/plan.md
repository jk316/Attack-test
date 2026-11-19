# 实施计划：PCAP 业务流量画像

**特性目录**: `specs/004-pcap-profile/` | **日期**: 2026-11-19 | **规格**: [spec.md](./spec.md)

**输入**: 来自 `specs/004-pcap-profile/spec.md` 的功能规格

## 摘要

为 PCAP 业务流量画像制定**回溯式**实施计划：PCAP/PCAPng 读取（Scapy rdpcap、前 N 包采样上限防内存爆炸）、UDP-only 统计口径（忽略 TCP/ICMP/非 IP 并在 notes 注明）、七类输出字段（top 排行 / 包长直方图 / IAT / 流数 / 负载统计 / notes）的主体能力**已实现**于 `src/tools/pcap_profile_tool.py`。本计划的工作内容是「现状 → 规格差距」的收敛改动：

- 修正 5 元组流键缺陷（现状误用 src_ip 代替 src_port，违反 FR-007 口径）；
- 补齐「无 UDP 流量」的显式说明（FR-009）；
- 按澄清默认（004-2 / 004-3）：维持顺序前 N 截断，采样上限与空闲阈值改为 `experiment.json` 统一配置、调用时读取（宪法「配置单一来源」）；
- 新增**确定性映射**能力（澄清 004-1）：画像 → Agent 初始流量参数（目标端口 / 包长 / 流数 / 发送节奏），显式 CLI 参数可人工覆盖。

技术方案维持现状选型：Scapy rdpcap 顺序读取 + 计数截断，不引入新解析依赖。

## 技术上下文

**语言/版本**: Python 3.11+（uv 管理依赖）

**主要依赖**: Scapy（`rdpcap` / `RawPcapReader`，解析 PCAP 与 PCAPng）；标准库（collections / statistics / pathlib）

**存储**: 无持久化——输入为抓包文件路径，输出为结构化画像字典/JSON；文件只读、不产生流量

**测试**: pytest（`uv run pytest tests/unit/ -v`）；用 Scapy 生成构造抓包（fixture）验证统计口径，用异常输入验证稳健性

**目标平台**: 跨平台（纯文件解析，无网络 I/O）；CLI 与 Web 上传两条入口共用同一工具

**项目类型**: CLI 实验 + Web 控制台共用的内嵌工具（`src/tools/`）

**性能目标**: 5 万包画像 2 分钟内、峰值内存 < 1 GB（SC-001，参考普通工作站）；读取按上限截断保证内存有界

**约束**: 采样上限（默认 50000，可配置）；只读不产流量；失败不崩溃（字段完整 + notes 说明）；反哺的初始参数仍受 allowlist / 参数上限 / HITL 门禁约束

**规模/范围**: 单文件分析；默认前 5 万包；top 排行各前 10；空闲阈值默认 30 秒

## 宪法检查

*门禁：阶段 0 研究前必须通过；阶段 1 设计后复查。*

| 宪法原则 | 检查结论 |
|---------|---------|
| 一、先想清楚再动手（计划先行） | ✅ 满足。spec.md 已评审，本文件即第二步；tasks.md 由 speckit-tasks 生成后才进入 implement。 |
| 二、闭环驱动（全流程收敛） | ✅ 满足。画像作为实验闭环「先画像、后攻击」的起点；确定性映射使「画像 → 参数」可审计、可复现，converge 阶段按 FR 复核。 |
| 三、测试伴随（新功能必配测试） | ✅ 满足（以实施为前提）。现有 `tests/unit/test_pcap_profile_tool.py` 需扩展；映射模块为纯函数，配套单元测试（G-004）；口径与异常路径以构造抓包测试固化（G-005~G-007）。 |
| 四、安全优先（不可协商） | ✅ 满足。画像只读分析、零流量；映射输出的初始参数在流量工具内部仍经 allowlist / 上限钳制 / HITL 三重门禁，映射不构成任何绕行。 |
| 五、可观测驱动（数据说话） | ✅ 满足。画像是观测输入端：用实测业务特征（而非猜测）确定初始参数；与 003 的 RTT 观测衔接构成完整反馈链。 |
| 六、配置单一来源 | ✅ 满足（以差距 G-003 实施为前提）。现状 `DEFAULT_COUNT_LIMIT=50000` 与 `idle_timeout=30` 为代码内默认值；经澄清 004-3 采纳后入 `experiment.json` → 环境变量 → 调用时读取。 |

阶段 1 设计后复查：无新增违反项；配置单一来源整改落入差距清单 G-003，确定性映射（G-004）不触碰安全门禁，其余原则在设计制品中保持。

## 项目结构

### 文档（本功能）

```text
specs/004-pcap-profile/
├── plan.md              # 本文件（speckit-plan 产出）
├── research.md          # 阶段 0 产出（澄清采纳与技术决策）
├── data-model.md        # 阶段 1 产出（实体、字段、映射规则）
├── quickstart.md        # 阶段 1 产出（端到端验证场景）
├── contracts/           # 阶段 1 产出
│   └── pcap-profile.md        # 画像 JSON 结构 + 反哺映射契约
└── tasks.md             # 阶段 2 产出（speckit-tasks 产出，非本步）
```

### 源代码（仓库根）

```text
src/
├── tools/
│   ├── pcap_profile_tool.py   # 现状：读取/统计主体；改动：5 元组修正（G-001）、无 UDP 说明（G-002）、配置读取（G-003）
│   └── profile_to_params.py   # 新增：确定性映射纯函数模块（G-004）
├── agent/tools.py             # 改动：pcap_profile 工具 count 默认值走 env（G-003）
├── main.py                    # 改动：注入 PCAP_PROFILE_* env；提供画像后以映射结果种子初始参数、CLI 显式参数优先（G-003/G-004）
└── config/experiment.json     # 改动：新增 "pcap_profile" 节（max_packets / idle_timeout_s）

backend/
└── experiment.py              # 改动：上传画像后复用同一映射路径（G-004）

tests/
└── unit/test_pcap_profile_tool.py   # 扩展：口径/异常/5 元组（G-001/G-005/G-006/G-007）
```

**结构决策**: 画像读取与统计留在 `pcap_profile_tool.py`（现状模块边界不变）；映射规则抽为独立纯函数模块 `profile_to_params.py`（无 I/O、便于单测与复用，CLI 与 Web 两条入口共用）；配置走既有流（experiment.json → main.py 设 env → 调用时读取），不新增存储或服务。

## 实施阶段

- **阶段 0 · 研究**：产出 `research.md`。三个澄清项按推荐默认采纳（004-1 确定性映射 + 人工覆盖、004-2 顺序前 N 截断维持、004-3 上限与阈值可配置），确认 Scapy 选型与测试策略。
- **阶段 1 · 设计**：产出 `data-model.md`、`quickstart.md`、`contracts/pcap-profile.md`（画像结构 + 映射契约）；完成后复查宪法检查（见上，无新增违反）。
- **阶段 2 · 任务生成**：由 speckit-tasks 依据本计划与差距清单产出 `tasks.md`（本步不创建）。

### 现状 → 规格差距清单（实施工作内容）

| 编号 | 关联 FR / SC | 现状 | 差距与改动 | 涉及文件 |
|------|-------------|------|-----------|---------|
| G-001 | FR-007、SC-005 | `calculate_flow_count` 的流键误写为 `(src_ip, src_ip, dst_ip, dst_port, 'UDP')`——src_port 位置被 src_ip 占据，同源多端口的流会被错误合并 | 修正为 5 元组 `(src_ip, src_port, dst_ip, dst_port, protocol)`；补构造抓包测试（同一 5 元组内 30 s 断流 → 新流；不同源端口 → 不同流） | `src/tools/pcap_profile_tool.py`、`tests/unit/test_pcap_profile_tool.py` |
| G-002 | FR-009 | 文件无任何 UDP 包时 notes 仅含默认口径文案，未显式说明「未发现 UDP 流量」 | 无 UDP 时追加显式说明（含被忽略的 TCP/ICMP/非 IP 数量），与 FR-009 一致 | `src/tools/pcap_profile_tool.py` |
| G-003 | FR-002、SC-002（澄清 004-3） | `DEFAULT_COUNT_LIMIT=50000`、`idle_timeout=30` 为代码内默认值/参数默认 | `experiment.json` 新增 `"pcap_profile"` 节：`max_packets=50000`、`idle_timeout_s=30`；main.py 注入 `PCAP_PROFILE_*` env；工具调用时读取（env 优先、回落默认） | `src/config/experiment.json`、`src/main.py`、`src/agent/tools.py`、`src/tools/pcap_profile_tool.py` |
| G-004 | FR-011（澄清 004-1） | 现状仅提示 LLM「先用 pcap_profile 分析流量特征」，参数选取完全由 LLM 自由发挥，不可复现 | 新增 `profile_to_params.py` 确定性映射：`dst_port=top_dst_ports[0]`、`packet_size=包长直方图中位数桶`、`flow_count=clamp(approx_flow_count, 1, 100)`、`pps` 由 IAT 均值换算并钳制到 `MAX_PPS`、`duration_s` 保持默认；映射值作为初始参数种子，CLI 显式参数（`--pps/--packet-size/--flow-count/--duration`）优先（人工覆盖）；Web 上传画像走同一映射 | 新增 `src/tools/profile_to_params.py`、`src/main.py`、`backend/experiment.py`、测试 |
| G-005 | FR-003、FR-012、SC-003 | UDP-only 过滤与忽略计数说明已实现 | 构造混合抓包（UDP+TCP+ICMP+非 IP）测试固化：被忽略包 100% 不进统计、notes 计数与实际一致 | `tests/unit/test_pcap_profile_tool.py` |
| G-006 | FR-006、SC-004 | IAT 按 (dst_ip,dst_port) 分组、排序后相邻差已实现 | 构造已知时间序列测试固化：mean/p50/p90 与手工计算一致（误差 ≤ 0.01 ms）、分组正确 | `tests/unit/test_pcap_profile_tool.py` |
| G-007 | FR-010、SC-006 | 异常路径（文件不存在/损坏/依赖缺失）已 try/except + notes | 异常输入批量测试固化：100 次随机异常输入零崩溃、字段完整、notes 非空 | `tests/unit/test_pcap_profile_tool.py` |

**现状已满足、无需改动**（仅由测试与 converge 复核）：FR-001 PCAP/PCAPng 读取、FR-002 截断与注明逻辑本体、FR-004 top10 排行、FR-005 分桶归一化、FR-008 负载统计、FR-012 口径隔离本体。

## 复杂度追踪

> 仅当宪法检查存在需论证的违反时填写

无违反项：本计划不引入超出宪法原则的复杂度，无需论证。
