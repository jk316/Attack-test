# 实施计划：TRex 集成与攻击目录探索

**特性目录**: `specs/006-trex-integration/` | **日期**: 2026-11-19 | **规格**: [spec.md](spec.md)

**输入**: 来自 `specs/006-trex-integration/spec.md` 的功能规格

## 摘要

把 Cisco TRex 客户端能力接入闭环实验 Agent：两个工具——`write_python_file`（脚本写入 `trex_scripts/` 沙箱 + 仅解析的语法检查）与 `run_python_file`（子进程执行，经「存在性 → 语法 → 静态 IP 筛查 → allowlist → HITL → 超时」门控链）；默认 dry-run 零流量，`--trex-live` 才执行；`--trex-explore` 为攻击目录探索模式——仅 2 个 TRex 工具、强制 dry-run（零流量零 HITL）、生成 ≥10 个带中文注释的 `cat_*.py` 脚本、目录摘要落盘 `output/trex_attack_catalog_<时间戳>.md`；`--trex-explore` 与 `--trex-live` 互斥。

本计划为**回溯式计划**：现有代码（`src/trex/tools.py`、`src/trex/config.py`、`src/prompts/trex_catalog_prompt.j2`、`src/main.py` 探索分支）已实现绝大部分规格，实施阶段以「现状 → 规格差距」清单为工作内容。

调研结论（详见 [research.md](research.md)）：三个澄清项按推荐默认采纳——接受 HITL 为唯一硬边界（静态 IP 筛查可被混淆，不追加检测）、探索预算耗尽未达 catalog_target 按非 0 退出码失败、cat_ 脚本采用显式清理参数（不自动清空）。

## 技术上下文

**语言/版本**: Python 3.11+（`uv` 管理依赖）

**主要依赖**: LangChain / LangGraph（`@tool`、`interrupt()` HITL）；标准库 `subprocess` 执行生成的脚本；Jinja2 渲染 `trex_catalog_prompt.j2`；TRex 客户端库（`trex_stl_lib`/`trex_astf_lib`）仅出现在**生成的脚本**中，由执行环境提供

**存储**: 文件——`trex_scripts/`（脚本沙箱）、`output/trex_attack_catalog_<时间戳>.md`（目录摘要）、`topology.yaml`（TRex host/port，默认 127.0.0.1:4501）

**测试**: pytest（`tests/unit/test_trex_tools.py` 已覆盖门控链 20+ 用例；`tests/unit/test_trex_catalog_mode.py` 已覆盖探索模式 19 用例）

**目标平台**: Linux / macOS / Windows（`subprocess` + `sys.executable` 跨平台；文件名保留字校验已含 Windows CON/PRN 等）

**项目类型**: CLI 闭环实验 Agent（LangGraph ReAct）+ Web 控制台；探索模式为独立 CLI 模式（mode="catalog"）

**性能目标**: dry-run 工具零执行、零审批（SC-001）；探索运行默认产出 ≥10 个语法通过的脚本（SC-007）；超时终止偏差 ≤+2s（SC-006）

**约束**: 脚本 ≤100000 字符 / ≤2000 行；输出截断 4000 字符；执行超时 (0, 300] 秒（默认 30）；静态 IP 筛查为 best-effort、HITL 为唯一硬边界；`--trex-explore` 与 `--trex-live` 互斥

**规模/范围**: 2 个工具、1 个配置模块、1 个提示词模板、1 个 CLI 探索分支；缺口改动集中在 `src/main.py` + 文档 + 测试

## 宪法检查

*门禁：阶段 0 研究前必须通过；阶段 1 设计后复查。*

| 宪法条目 | 结论 | 说明 |
|---------|------|------|
| 一、先想清楚再动手 | ✅ 满足 | 本计划即计划产物；spec.md 先于实现存在 |
| 二、闭环驱动 | ✅ 满足 | 实验模式 run_python_file 提供 target_ip 时附 RTT 观测（FR-011）；探索模式以「规划→生成→校验→总结落盘」闭环产出目录资产 |
| 三、测试伴随 | ✅ 满足（含缺口） | 现有单测覆盖门控链与探索模式；缺口 G4 的退出码/清理参数必须补测试 |
| 四、安全优先 | ✅ 满足 | 门控链（FR-005–010）现状完整且测试覆盖；HITL 为唯一硬边界、静态筛查为辅助已如实声明（决策 006-1）；探索模式结构上零流量零 HITL（graph.py 仅注册 TREX_TOOLS 且强制 dry-run） |
| 五、可观测驱动 | ✅ 满足 | live 执行带 target_ip 时附 RTT 观测与窗口覆盖校验；执行结果含返回码/输出/耗时 |
| 六、配置单一来源 | ✅ 满足 | `src/trex/config.py` 每次调用重读 env（TREX_HOST/PORT/TIMEOUT_S/DRY_RUN），拓扑回退链完整（FR-022） |
| 附加约束·参数上限 | ✅ 满足 | 脚本规模上限（100k 字符/2000 行）、超时钳制 (0,300] 已实现 |
| 附加约束·跨平台 | ✅ 满足 | 子进程经 `sys.executable` 启动；文件名保留字校验跨平台 |
| 附加约束·文档真实性 | ✅ 满足（含缺口） | 工具说明已如实声明「静态筛查非硬边界」「无 OS 级沙箱」；缺口 G3 仅核对审批材料提示 |

结论：**门禁通过**——无未论证的违反；缺口均为规格口径细化（退出码、清理参数、提示措辞），不改变安全架构。

## 项目结构

### 文档（本功能）

```text
specs/006-trex-integration/
├── plan.md                       # 本文件（speckit-plan 产出）
├── research.md                   # 阶段 0 产出（决策 D1–D5）
├── data-model.md                 # 阶段 1 产出（5 个关键实体）
├── quickstart.md                 # 阶段 1 产出（端到端验证场景）
├── contracts/
│   ├── trex-script-sandbox.md    # 脚本沙箱契约（文件名/规模/语法检查）
│   └── trex-run-gates.md         # 运行门控链与探索达标契约
└── tasks.md                      # 阶段 2 产出（speckit-tasks，非本步）
```

### 源代码（仓库根，现状与改动位置）

```text
src/trex/tools.py                  # 现状已满足 FR-001~011，不改动（契约来源）
src/trex/config.py                 # 现状已满足 FR-022，不改动
src/agent/graph.py                 # 现状已满足 FR-012（mode=catalog → TREX_TOOLS + 强制 dry-run），不改动
src/prompts/trex_catalog_prompt.j2 # 现状已满足 FR-013~017/019/021，不改动
src/main.py                        # 缺口 G1（探索达标校验+非 0 退出码）、G2（--clean-scripts）的改动位置
tests/unit/test_trex_catalog_mode.py  # 扩展：G1/G2 用例
tests/unit/test_trex_tools.py         # 现状已覆盖门控链，核对即可
```

**结构决策**: 工具层与提示词层现状即规格，缺口只落在 CLI 编排层（`src/main.py`）——达标统计与清理参数都属于「探索模式生命周期」职责，与工具语义无关；配置 getter 保持每次调用重读 env 的既有模式。

## 实施阶段

- **阶段 0 · 研究**：产出 `research.md`。研究项：R1 HITL 唯一硬边界口径（→决策 D1）；R2 未达标退出码方案（→D2）；R3 cat_ 脚本清理策略（→D3）；R4「不得提前结束」的强制层级（→D4）；R5 现状确认（→D5）。**已完成**。
- **阶段 1 · 设计**：产出 `data-model.md`、`quickstart.md`、`contracts/`（2 份契约）；完成后复查宪法检查（结论见上表）。**已完成**。
- **阶段 2 · 实现差距**（回溯式：现状 → 规格差距清单，由 speckit-tasks 拆任务）：

| 编号 | 对应 FR/决策 | 现状 | 差距动作 | 验收口径 |
|------|-------------|------|---------|---------|
| G1 | FR-016/FR-021 + 决策 006-2 | 探索结束仅落盘摘要，退出码恒 0，不核对达标数量 | main.py 探索结束后对 `trex_scripts/cat_*.py` 逐一做语法检查并计数：≥catalog_target → 退出码 0；未达标 → 仍落盘总结（FR-021）但退出码非 0；`--catalog-target` <1 在解析期拒绝报错（D6） | 未达标运行返回非 0 退出码且总结已落盘；`--catalog-target 0` 启动即报错 |
| G2 | 决策 006-3 | 无清理机制，cat_ 脚本持续累积 | 新增 `--clean-scripts`（bool，默认 False）：探索模式启动时若设置，仅删除 `trex_scripts/cat_*.py`（绝不动其他文件），并在启动横幅打印清理行为 | 设置后旧 cat_ 脚本被清空、非 cat_ 文件完好 |
| G3 | FR-009 + 决策 006-1 | 审批材料已有「完整权限执行、无执行沙箱」警告 | 核对并在审批材料中补充「静态 IP 筛查可被混淆绕过，请人工审查脚本」提示 | 审批材料完整披露风险 |
| G4 | 宪法三 | 缺 G1/G2 行为测试 | `test_trex_catalog_mode.py` 扩展：退出码判定（达标/未达标）、清理参数只删 cat_ 前缀 | `uv run pytest tests/ -v` 全绿 |

已满足无需改动（核对即可）：FR-001~015、FR-017~020、FR-022 均有实现且大部分有单测（test_trex_tools.py / test_trex_catalog_mode.py）。

- **阶段 3 · 任务生成**：由 speckit-tasks 依据本计划产出 `tasks.md`（本步不创建）。

## 复杂度追踪

> 仅当宪法检查存在需论证的违反时填写

无需要论证的违反——静态 IP 筛查的 best-effort 性质是设计声明而非违反（HITL 为硬边界，且已在审批材料中披露）。表格留空。
