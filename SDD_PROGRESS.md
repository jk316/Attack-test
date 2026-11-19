# SDD 177 任务监督账本

> Team Lead（watchdog）维护。任务来源：`specs/*/tasks.md`，共 8 个特性 177 个任务。
> 执行方式：实现队友分两梯队顺序执行（001–004 → 005–008），Lead 逐特性验收（勾选核对 + 测试复核 + 提交核对）。

## 总览

| 特性 | 任务数 | 已完成 | 勾选一致 | 测试 | 提交 | 验收状态 |
|------|-------:|-------:|:--------:|:----:|:----:|:--------:|
| 001-agent-core | 25 | 25 | ✅ | 447P/9F(基线) | 191c4aa | ✅ 已验收（T014 补勾+2 裁定） |
| 002-scapy-traffic-tools | 25 | 25 | ✅ | 506P/9F(基线) | cbc3e84 | ✅ 已验收（R6 quickstart 文档修复） |
| 003-ping-monitor-rtt | 21 | 20 | ✅(T018 改派) | 548P/9F(基线) | 1d5d615 | ✅ 已验收（T003/T004 补勾 + T018→007） |
| 004-pcap-profile | 24 | 23 | ✅(T017 改派) | 586P/9F(基线) | 4f4bb01 | ✅ 已验收（T017→007） |
| 005-pktgen-integration | 21 | 19 | ✅(T012/13 待 008 回补) | 624P/1F/11S | c846824 | ✅ 已验收（R10 文档修订） |
| 006-trex-integration | 17 | 17 | ✅ | 671P/1F/11S | 10a5ac9 | ✅ 已验收（R10 已并入） |
| 007-web-console | 24 | 24 | ✅ | 719P/1F/11S | e36eab5 | ✅ 已验收（R7/R8 关闭） |
| 008-security-config | 20 | 20 | ✅ | 809P/0F/11S | f9f7112 | ✅ 已验收（首次全绿） |
| **合计** | **177** | **177** | ✅ | **809P/0F/11S (90%)** | 13 commits | ✅ **全部验收** |

## 裁定记录（Rulings）

- **S1（安全事件，007 实现期间）**：tests/integration/test_hitl_flow.py 初版 approve 用例中 `patch("src.agent.tools.traffic_send_tool")` 的 with 块在 manager.start 之前退出 → HITL 批准后落到真实工具，向 allowlist 目标 10.99.80.160 以 pps≈50 发送约 10s UDP（推断 ~500 包），无 HITL。队友如实主动披露并立即修复（patch 覆盖全生命周期 + 安全红线注释，修复后 2 用例 0.89s 通过）。Lead 复核：无残留进程；全仓库 patch 用法审计无同类缺陷；判定孤例、已修复、影响面小（allowlist 实验目标、低速率）。**将在最终验收报告向用户如实披露。**
- **R11（防再发约定）**：所有「实验生命周期类」测试（graph invoke / manager.start / main 主循环）必须让流量工具 mock 覆盖从构造到结束的整个生命周期，并在测试内保留「安全红线」注释；Lead 每次特性验收独立抽查。- **R1（清单门禁）**：001–004 的 `checklists/requirements.md` 存在未勾选项（共 73 项）。用户已将审批策略改为「永不询问」，即授权不阻塞推进。裁定：**不阻塞、不修改任何清单文件**（清单归评审者所有），实现照常进行；实现中若发现真实规格缺口，立即上报。代价：若清单项背后真有规格缺陷，需在实现中返工——可接受，因为缺陷同样会暴露在测试/验收中。
- **R2（并行策略）**：001–008 在 `src/main.py`、`src/agent/tools.py`、`src/config/experiment.json`、`backend/experiment.py` 等多处共享文件上高度耦合，无法安全并行。裁定：**两梯队顺序执行**（001–004 先，005–008 后），换取零写冲突；代价是墙钟时间串行——可接受，监督质量优先。
- **R3（勾选格式）**：tasks.md 统一用 `- [x]` 勾选（与现有 checklist 格式一致）；验收统计同时接受 `[x]`/`[X]`。
- **R4（ATK_IAT_JITTER_MS 注入归属）**：001-T002 发现 main.py 未注入 `ATK_IAT_JITTER_MS`（无对应 CLI 参数）。裁定归属 **002**（T015 实现 env 读取 + experiment.json 已有键）：由 002 在 T015/T016 后补齐 main.py 注入行（配置链取值、profile 感知、不新增 CLI 参数）+ 断言测试。理由：不注入则该配置键永不生效，违反宪法「配置单一来源」。
- **R5（001-T023 真实 LLM 验证）**：~~.env 密钥无效~~ → **已关闭（2026-11-19 08:09）**。根因：会话位于 git worktree，误读了 worktree 内 01:37 的旧截断密钥（29 字符）；用户的有效密钥在主仓库 `/Users/zxkkk/code/Attack-test/.env`（35 字符 + LLM_MODEL=deepseek-flash，与账户模型 deepseek-flash/deepseek-v4-pro 匹配）。修复：worktree .env → 符号链接指向主仓库 .env。真实 LLM 补验：场景 C 目录探索实跑（17 脚本、exit 0、零流量）+ 场景 A 实验模式实跑（HITL 全拒 0 报文、covers=false 轮硬裁决跳过、exit 0）。场景 B（auto-approve 真实流量）与 002 场景 A（真实流量命令）按安全红线维持 mock 等价、不实跑。
- **R6（002 quickstart 直接脚本命令）**：`python src/tools/traffic_send_tool.py` 直接运行因相对导入失败（预存在）。裁定归属 002 收尾：quickstart.md 命令改 `-m` 模块形式（或等价写法），纯文档修复，可并入 003/004 任意提交。
- **R7（003-T018 改派）**：Web 端 ping 监控清理（backend/experiment.py 实验结束路径调 `get_ping_monitor().stop()`，FR-016/G-003）在 003 梯队范围外（禁改 backend/）。裁定：保持未勾，改派 **007 梯队**（第二梯队），已写入第二梯队任务书。
- **R8（004-T017 改派）**：Web 上传画像映射接入（backend/experiment.py 走 `profile_to_params` 注入会话上下文）同属 backend/ 范围冲突。裁定：保持未勾，改派 **007 梯队**（第二梯队），已写入第二梯队任务书。
- **R9（logger 测试污染）**：第二梯队 005-T001 发现单进程全量 `tests/` 下 test_verbose_callback 多出 8 失败——main() 日志初始化（agent logger propagate=False + addHandler 不恢复）污染后续 caplog 断言，顺序敏感（Lead 此前显式目录顺序恰好掩盖）。裁定：tests/conftest.py 加 autouse fixture 快照/恢复 logger（纯测试侧、零行为代码改动），由第二梯队执行；**全量门禁统一改用 `bash .dsh/run-tests.sh tests/ -q` 单进程标准入口**；005 内另修 pktgen conftest 跳过逻辑与 17→19 断言 → 005 门禁预期仅剩 1 个既有失败（test_agent_graph，留 006/008）。
- **R10（005 quickstart 场景 3 措辞）**：vendored 编译器对 seqTable 只发占位注释，编译产物不含逐条目 MAC（D8 禁改 vendored）。裁定：修订 005 quickstart.md 措辞为可观测行为（adapter replaced_mac 明细 + params 级真实 MAC），纯文档修复，并入第二梯队后续提交。

## 事件日志

- 2026-11-19 01:30 初始核查：177/177 未勾选；`compute_reward` 仍为旧公式（001-T004 目标）；001 引用的 12 个测试文件均不存在 → 勾选状态与代码现实一致，执行未开始。
- 2026-11-19 01:31 提交 SDD 制品基线 commit `3c08913`；启动全量基线测试（后台）。
- 2026-11-19 01:31 派出第一梯队实现队友 `impl-first-half`（001–004）。
- 2026-11-19 01:32 **环境问题定位并修复**：`uv run pytest` 静默回退到系统 Python 3.9 的 pytest（PATH 污染 + .venv 缺 pytest）。根因：dev 依赖未同步。修复：`uv sync --extra dev`（venv 内 pytest 9.0.3）。已通知实现队友重跑基线。→ 教训：环境必须先验证 `uv run python -V` == 3.13.x + `uv run pytest --version` == venv 版。
- 2026-11-19 01:39 **干净环境全量基线：346 通过 / 9 失败**（commit `7be0181`）。9 个失败全部归类为既有失败：① 2× 工具计数断言过期（期望 17，现实 19，CLAUDE.md 确认 19 正确）→ 预计 005/006/008 修复；② 7× pktgen client 直连真实硬件被 reset → 预计 005 修复 conftest 跳过逻辑。已把完整基线报告发给实现队友供 T001 记录。
- 2026-11-19 01:41 **用户填好 .env 后的环境复核**：① .env 存在，`DEEPSEEK_API_KEY` 长度 29（标准应为 35 = sk- + 32 位）→ 真实 API 冒烟测试返回 **401 密钥无效**（代理与直连均能到达 api.deepseek.com，网络无问题，密钥本身无效/疑似截断）。② 宿主 shell 的 `no_proxy` 含 `[::1]` 条目 → httpx 0.28.1 解析崩溃（`InvalidURL: Invalid port ':1]'`），影响任何真实 LLM 调用（运行时级环境问题，来源不在仓库 .zshrc 的 sync_proxy 函数内，疑似系统/代理工具注入）；清理后调用路径正常。③ 对 177 任务实现无阻塞：测试全走 mock + `.dsh/run-tests.sh` 已剥离代理；**影响点**：001-T023 quickstart 真实验证与最终手动运行。待用户修复密钥与 no_proxy（建议去掉 `[::1]`/`::1`，127.0.0.1/localhost 已覆盖回环）。
- 2026-11-19 01:54 **001 验收通过**：实现队友报告 25/25、447P/9F（9 个均为基线失败）。Lead 独立复核一致：全量 447 passed / 9 failed、commit `191c4aa` 范围干净（src/agent、src/main.py、prompts、tests、文档，无越界）、净增 101 用例。发现 T014 勾选遗漏（文件已在提交）→ 要求补勾；裁定 R4（ATK_IAT_JITTER_MS 注入归属 002）与 R5（T023 真实 LLM 待密钥修复后补验）。队友已开始 002。
- 2026-11-19 02:24 **002 验收通过**：25/25、506P/9F（基线）。Lead 独立复核一致：commit `cbc3e84` 范围干净（src/tools、src/agent/tools.py、src/main.py、prompts、tests、文档）、净增 79 用例；R4 注入实现核查通过；T025 场景验证守安全红线（未跑真实流量）。裁定 R6（quickstart 直接脚本命令改 `-m` 形式，文档修复并入后续提交）。队友已开始 003。
- 2026-11-19 02:39 **003 验收通过**：20/21 + T018 改派。Lead 独立复核：548P/9F（基线）、commit `1d5d615` 范围干净、净增 76 用例。发现 T003/T004 漏勾（代码已提交）→ 要求补勾（已随 `650b960` 完成）；裁定 R7（T018 Web 端监控清理改派 007 梯队）。队友已开始 004（本梯队最后一个）。
- 2026-11-19 02:48 **004 验收通过，第一梯队收官**：23/24 + T017 改派。Lead 独立复核：586P/9F（基线）、commit `4f4bb01` 范围干净、净增 38 用例。裁定 R8（T017 Web 画像映射接入改派 007 梯队）。第一梯队成果：93/95 任务完成 + 2 项 backend/ 范围冲突按协议改派；四特性全量门禁 586P/9F（无新增回归）、覆盖率 89%。派出第二梯队 `impl-second-half`（005–008 共 82 任务 + R7/R8 两项遗补），移交基线 586P/9F 与 9 个既有失败的修复归属说明。
- 2026-11-19 02:57 第二梯队 005-T001 开工报告：确认移交基线 566P/9F（单元+集成）+20 e2e ✓；发现全量单进程污染（test_verbose_callback +8F）→ 裁定 R9（conftest autouse fixture + 全量门禁统一 `tests/` 入口）；批准其 pktgen conftest 修复方案（connect+服务探测→skip、bad_host mock 化、17→19 断言）。
- 2026-11-19 03:09 **005 验收通过**：19/21（T012/T013 按任务书阻塞至 008 回补）。Lead 独立复核：624P/1F/11S 一致；commit `c846824` 范围干净；experiment.json 语义比对仅新增 pktgen.src_ip。裁定 R10（quickstart 场景 3 措辞修订）；④ 契约观察归 008-G3。队友已开始 006。
- 2026-11-19 03:20 **006 验收通过**：17/17。Lead 独立复核：671P/1F/11S 一致；commit `10a5ac9` 范围干净；净增 47 用例；R10 已并入。队友已开始 007（含 R7/R8 遗补）。
- 2026-11-19 03:33 **007 验收通过**：24/24 + R7/R8 关闭。Lead 独立复核：719P/1F/11S 一致；commit `e36eab5` 范围干净；R7（幂等清理 + finally/主动 stop 调 get_ping_monitor().stop()）与 R8（profile_to_params 映射注入 user message）落点核实；003→21/21、004→24/24 改派项正式关闭；S1 整改 R11 到位。队友已开始 008（最后一棒：清零 test_agent_graph 断言 + ④ 契约 + 回补 005 T012/T013）。
- 2026-11-19 03:39 **008 验收通过，177/177 全部收官**：20/20 + 005 T012/T013 回补完成。Lead 终验：8 特性勾选 177/177 零未勾；清单文件全程未动；提交链 13 commits 完整；全量单进程终测 **809P/0F/11S（首次全绿，9 个基线失败全部清零，净增 463 用例），覆盖率 90%**。③④ 决策以 008 权威契约为准已记账。**剩余待办仅 R5**：真实 LLM quickstart 场景补验，待用户修复 .env 密钥（当前 29 字符仍无效）。S1 事件将在最终报告向用户披露。
- 2026-11-19 08:09 **R5 密钥谜团解决 + 真实 LLM 补验完成**：根因 = 会话在 git worktree，误读 worktree 旧 .env（29 字符截断密钥）；用户有效密钥在主仓库（35 字符 + LLM_MODEL=deepseek-flash，与账户模型 deepseek-flash/deepseek-v4-pro 匹配）。修复：worktree .env → 符号链接主仓库 .env（commit `c144a11`）。真实 LLM 实测：目录探索 17 脚本 exit 0；实验模式 HITL 全拒 0 报文、covers=false 轮硬裁决跳过、exit 0。
- 2026-11-19 09:45 **Web 控制台真实验证 15/15 通过**（脚本 `.dsh/verify-web.py`，真实 LLM + 真实服务）：REST（页面/status/defaults/start 400 校验）、PCAP 上传白名单（.txt 拒绝）、WS 实验全流程（真实 LLM 规划参数并消费上传画像映射 R8：dst_port=53/packet_size=128）、hitl_request 统一 {message,params,scope}、**007-2 非所有者审批被拒「非会话所有者」**、所有者拒绝 → 0 流量、experiment_done、状态复位、**无残留监控进程（R7）**。服务已停止、无残留进程。
