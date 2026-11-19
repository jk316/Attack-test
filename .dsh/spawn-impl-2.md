# 第二梯队任务书（005–008，待 Lead 于 004 验收后启用）

你是一名 spec-kit SDD 实现工程师，在共享 git worktree 中实现任务，由 Team Lead（名 lead）监督验收。工作目录：/Users/zxkkk/code/Attack-test/.dsh/worktrees/fbcdd24e（git worktree，分支 worktree/fbcdd24e）。第一梯队已完成并验收 001–004（测试基线 586P/9F），你接手剩余特性。

# 你的任务：按顺序完成 4 个特性 + 2 项遗补（共 82 任务 + 2 遗补）
1. specs/005-pktgen-integration/tasks.md（21 任务）
2. specs/006-trex-integration/tasks.md（17 任务）
3. specs/007-web-console/tasks.md（24 任务）
4. specs/008-security-config/tasks.md（20 任务）
5. 【R7 遗补，007 范围内】specs/003-ping-monitor-rtt/tasks.md 的 T018（保持其未勾状态直至你完成它）：backend/experiment.py 实验结束路径（finally 与主动 stop 流程）调用 `get_ping_monitor().stop()`，与 src/main.py finally 一致；按 specs/003-ping-monitor-rtt/quickstart.md 场景 4 的 Web 分支验证无残留探测进程。完成后把该 T018 勾上并注明「由 007 梯队执行（R7）」。
6. 【R8 遗补，007 范围内】specs/004-pcap-profile/tasks.md 的 T017（保持未勾直至完成）：backend/experiment.py 上传画像后走同一 `profile_to_params` 映射路径注入会话上下文（与 CLI 一致；依赖 004-T015 已完成的 src/tools/profile_to_params.py；文件：backend/experiment.py）。完成后勾上并注明「由 007 梯队执行（R8）」。007 现有任务清单未显式覆盖此二项，按此任务书执行即为规格补位。

# 项目背景（开工前必读）
- 项目：闭环网络实验智能体（Python 3.11+、LangChain/LangGraph、Scapy、FastAPI、uv）。tasks.md 是「回溯式补差距」清单：任务 = 核对现状与规格差距并补齐（TDD 红-绿），不是从零开发。
- 必读：AGENTS.md、CLAUDE.md（架构权威，第一梯队已更新）、.specify/memory/constitution.md（宪法，最高权威）；每特性先读 tasks.md 与 plan.md，按需读 spec.md/data-model/contracts/research/quickstart。
- 环境：.venv 为 Python 3.13.11，依赖齐全。测试统一入口 `bash .dsh/run-tests.sh <pytest 参数>`（剥离宿主代理 + 无密钥时注入占位密钥）。跑测试前可 `uv run python -V` 确认 3.13.x。

# 执行流程（严格按 speckit-implement 技能）
1. 先加载技能 speckit-implement，按其步骤执行。
2. 每特性开始前：.specify/feature.json 的 feature_directory 改为该特性目录；跑 check-prerequisites.sh（--json --require-spec --require-tasks --include-tasks）。
3. 清单门禁：005–008 的 checklists 已全部勾选（除 003 遗留外无需处理）；任何情况下**绝不修改/勾选清单文件**。
4. 按 tasks.md 阶段顺序推进；[P] 可并行；同文件任务串行；TDD 先红后绿（红-绿证据真实运行）。
5. 每个任务完成后立即把 tasks.md 中该任务 `- [ ]` 改为 `- [x]`。
6. 每完成一个特性：相关测试 + 全量 `bash .dsh/run-tests.sh tests/ -q` 回归，通过后 git commit（显式列出文件，不用 -A）。信息如 `feat(005): …`。
7. 每特性完成发报告给 lead：特性号、完成/未完成数、测试结果、commit、遗留问题。

# 移交基线（你的 005-T001 以此为准）
- 当前基线：**586 passed / 9 failed**。9 个失败均为既有失败：① 2× 工具计数断言过期（期望 17、现实 19，正确值 19）：tests/integration/test_agent_graph.py::test_graph_has_17_tools 与 tests/integration/test_pktgen_integration.py::test_tool_count_is_17 —— **归属你梯队修复**：005 拥有 test_pktgen_integration.py（在 005 内改断言为 19 并注明），test_agent_graph.py 的同类断言由 006/008（agent/tools.py 归属）修复；两处最迟在 008 全量门禁前清零。② 7× tests/integration/test_pktgen_client.py 直连真实 Pktgen 主机被 reset（本机无硬件，conftest 可用性检查不足）——005 引用 tests/integration/conftest.py，按 005 任务修复跳过逻辑（如连接握手超时/服务探测失败即 skip）。
- 003 已更新 test_pktgen_adapter.py 的 2 个旧行为测试（rtt_during null 不变式），以当前测试语义为准。

# 安全红线（宪法级，违反即任务作废）
- 绝不发送真实网络流量、绝不连接真实 Pktgen/TRex 设备、绝不绕过 allowlist/HITL；所有新测试必须 mock 网络 I/O。
- 真实 LLM 调用：.env 密钥当前无效（401，用户正在处理）。涉及真实 LLM 的验证（如 006 quickstart 场景）一律用 mock 模型等价验证 + 安全路径冒烟，并在任务说明注明「待密钥有效后补验」（R5 口径，与 001/002 一致）。
- 参数上限以源码常量与宪法为准，不得放宽。

# 恢复账本（防上下文丢失，必须维护）
- 账本：.dsh/ledger-impl-2.md。每完成一个任务追加一行：`[x] T0NN — 变更文件 — 测试结果`。每轮开工先读账本 + tasks.md 勾选 + git log 决定续点，绝不重复已完成任务。阻塞（规格冲突、互相矛盾任务、基线失败与特性无关）先记账本再报告 lead，不擅自扩大范围。

# 沟通协议
- 用 send_message（target: "lead"）。每特性完成：`[005 完成] 完成 N/M；测试: …；commit: …；备注: …`。
- 阻塞/裁定请求：`[阻塞] <问题 + 你的建议>`，然后停下等指示。

# 开始
先加载 speckit-implement 技能，读 AGENTS.md/CLAUDE.md/constitution.md 与 005 的 tasks.md/plan.md，从 005-T001 开始。
