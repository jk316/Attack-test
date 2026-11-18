---
description: "Web 控制台（实时实验监控与人工审批）实现任务列表"
---

# 任务：Web 控制台（实时实验监控与人工审批）

**输入**: 来自 `specs/007-web-console/` 的设计文档（spec.md、plan.md、research.md、data-model.md、contracts/ws-messages.md、contracts/rest-api.md、quickstart.md）

**前置**: spec.md（用户故事来源）、plan.md（差距 G1–G6）

**组织方式**: 任务按用户故事分组，使每个故事可独立实现与测试。本特性为**回溯式**：现状已有一版实现（backend/server.py、backend/experiment.py、frontend 三件套），任务内容 = plan.md 中 G1–G6 差距的落地，多含「先写测试暴露缺口、再实现」的任务。

## 任务总览

| 任务 ID | 阶段 | 所属故事 | 可并行 | 说明 |
|---------|------|---------|--------|------|
| T001 | 1 搭建 | — | 否 | 运行现有测试基线并记录 |
| T002 | 1 搭建 | — | 否 | backend 测试基座确认（import 通路） |
| T003 | 1 搭建 | — | 是 | _msg_to_dict 基线单测（backend 首批测试） |
| T004 | 2 地基 | — | 否 | G2 per-client_id 会话注册表重构（backend/experiment.py） |
| T005 | 2 地基 | — | 否 | G2 会话所有者校验（backend/server.py，依赖 T004） |
| T006 | 2 地基 | — | 否 | 会话互斥/归属单测（依赖 T004/T005） |
| T007 | 3 | US1 | 是 | HITL 闭环集成测试（先写） |
| T008 | 3 | US1 | 是 | 消息流顺序/类型单测（先写） |
| T009 | 3 | US1 | 否 | _extract_hitl 兼容统一审批结构 |
| T010 | 3 | US1 | 否 | 前端审批弹窗明细+拒绝展示+摘要渲染（app.js） |
| T011 | 3 | US1 | 是 | resume=False 零流量语义单测 |
| T012 | 4 | US2 | 是 | PCAP 上传校验测试（先写，现状失败） |
| T013 | 4 | US2 | 是 | 默认值接口测试（先写，现状失败） |
| T014 | 4 | US2 | 否 | G3 上传服务端校验（backend/server.py） |
| T015 | 4 | US2 | 否 | G4 默认值接口+StartRequest 兜底与参数校验（backend/server.py） |
| T016 | 4 | US2 | 否 | G4 前端默认值拉取+启动被拒复位（frontend/app.js、index.html） |
| T017 | 4 | US2 | 否 | 状态/停止会话语义集成测试 |
| T018 | 5 | US3 | 是 | 断线清理与错误消息测试（先写） |
| T019 | 5 | US3 | 否 | 断线提示与重连引导（frontend/app.js） |
| T020 | 5 | US3 | 否 | G5 统计卡数据源处理（frontend/app.js、index.html，依赖 T019） |
| T021 | 5 | US3 | 是 | G1 页面内网声明横幅（frontend/index.html、style.css） |
| T022 | 6 打磨 | — | 是 | G1 README 安全声明 |
| T023 | 6 打磨 | — | 是 | G1 启动日志内网限定警告（backend/server.py） |
| T024 | 6 打磨 | — | 否 | G6 全量回归 + quickstart 验收 + SC/FR 收敛打勾 |

## 格式：`[ID] [P] [故事] 描述`

- **[P]**: 可并行（不同文件、无依赖）
- **[故事]**: 所属用户故事（US1/US2/US3）
- 描述中包含确切文件路径

## 阶段 1：搭建（基线确认）

**目的**: 确认现状测试基线；backend 当前无任何测试，先建立最小可运行的 backend 测试通路

- [ ] T001 在项目根运行 `uv run pytest tests/ -v`，记录基线结果；若存在失败，仅做最小修复使基线全绿（不得借机改产品逻辑），并把结果记入本任务的提交说明
- [ ] T002 确认 backend 可测试通路：验证 `uv run python -c "import backend.experiment, backend.server"` 在项目根可执行；核对 tests/unit/conftest.py 已将项目根加入 sys.path（按 CLAUDE.md「Test Organization」约定），如缺则补齐该 conftest（文件：tests/unit/conftest.py）
- [ ] T003 [P] 在 tests/unit/test_experiment_msg.py 为 backend/experiment.py 的 `_msg_to_dict` 写基线单元测试：给定含 tool_calls 的 LangChain 消息，断言输出含 role/content/tool_calls（name+args）；给定无 tool_calls 消息断言 tool_calls 为 None。先跑一次记录现状结果（预期通过，若失败记入缺口）

**检查点**: 基线全绿、backend 可被 pytest 导入

## 阶段 2：地基（阻塞性前置）

**目的**: 007-2 决议「单客户端会话模型」是 US1 审批归属、US2 启停互斥、US3 断线语义的共同前提，必须先落地

**⚠️ 关键**: 本阶段完成前不得开始任何用户故事工作

- [ ] T004 将 backend/experiment.py 的 ExperimentManager 由进程级单例重构为 per-client_id 会话注册表（映射 client_id → 会话对象，会话内持实验运行/审批队列/所有者）；保留 `graph.ainvoke` 桥接、`_push_new_messages`、`_extract_hitl`、`approve`/`stop` 既有逻辑；同一 client_id 已有运行实验时再次 start 返回「实验已在运行中」（FR-009 按会话粒度）。对照 data-model.md「控制台会话/实验运行」字段与状态流转（idle→starting→running→done/stopped/error）
- [ ] T005 在 backend/server.py 的 websocket_endpoint 中为 hitl_response 与 stop_experiment 增加会话所有者校验：非发起实验的 client_id 发送这两类消息时返回 error（"非会话所有者"）且不改变实验状态（007-2 决议、contracts/ws-messages.md 总则第 3 条）。依赖 T004
- [ ] T006 在 tests/unit/test_experiment_sessions.py 写会话模型单元测试：同 client_id 二次 start 被拒；B 客户端的 hitl_response/stop_experiment 对 A 会话无效且收到 error；A 客户端自己的决定生效。依赖 T004/T005

**检查点**: 会话模型就绪——用户故事可以开始并行实现

## 阶段 3：用户故事 1 - 实时观察实验并完成人工审批（优先级：P1）🎯 MVP

**目标**: 操作员实时观察消息流（AI 消息/工具结果/生命周期），并在 HITL 弹窗中批准/拒绝；门禁不可绕过（未决定不放行、拒绝即中止、服务端无自动批准路径）

**独立测试**: quickstart.md 场景 1/5/6——连接确认、消息流逐条到达、审批批准→继续、拒绝→中止、不操作 60s 仍暂停；SC-003/004/005 断言

### 用户故事 1 的测试（先写测试，确认失败后再实现）⚠️

> **注意：先写测试，确认失败后再实现**

- [ ] T007 [P] [US1] 在 tests/integration/test_hitl_flow.py 写 HITL 审批闭环集成测试：构造最小执行（mock LLM 触发一次含 interrupt 的工具调用，参照 tests/e2e 现有模式），断言 ① hitl_request 推送（data 含 message+params，契约见 contracts/hitl-payload.md）② 队列回填后 resume 决定送达 ③ 拒绝时该工具结果标记「被操作员拒绝」且无流量（FR-011~FR-014、SC-004/005）
- [ ] T008 [P] [US1] 在 tests/unit/test_experiment_stream.py 写消息流顺序/类型单测：mock graph 状态快照，断言 `_push_new_messages(since)` 从 since 起无遗漏、tool 角色映射为 tool_result、其余映射为 messages、最终推送 experiment_done（FR-004~FR-006）

### 用户故事 1 的实现

- [ ] T009 [US1] 在 backend/experiment.py 确认并适配 `_extract_hitl` 与统一审批结构（contracts/hitl-payload.md）兼容：定位规则保持「dict 且含 message 键」；hitl_request.data 透传 message/params/scope 原样（scope 为 008 新增字段，兼容旧 payload 无 scope 的情况，不报错）
- [ ] T010 [US1] 在 frontend/app.js 完善审批闭环展示：① 审批弹窗展示 message + params 明细（含 scope 字段）② 拒绝后面板明确显示「HITL 审批拒绝」（核验现状并补全）③ experiment_done 携带 summary 时渲染摘要文本（现状只显示「实验完成」）；对照 contracts/ws-messages.md 的渲染与截断约束（内容转义、AI≤1000/工具结果≤300/摘要≤2000 字符）
- [ ] T011 [P] [US1] 在 tests/unit/test_hitl_semantics.py 写 resume=False 零流量语义单测：对 ExperimentManager 会话的 approve(False) 路径断言注入的决定为 False（`Command(resume=False)` 语义），并在工具层断言拒绝返回 `{"success": false, "error": "HITL rejected by operator"}`（与 008 契约一致）

**检查点**: 用户故事 1 完整可用且可独立测试（quickstart 场景 1/5/6 通过）

## 阶段 4：用户故事 2 - 配置、启停实验与 PCAP 上传（优先级：P2）

**目标**: 表单默认值取自 experiment.json（单一来源）；上传服务端强制类型/大小校验；启停互斥；状态查询

**独立测试**: quickstart.md 场景 2/3/4/7——默认值与配置一致、非法扩展名/超大文件被拒且不落盘、二次启动被拒、停止复位、状态查询与面板一致

### 用户故事 2 的测试（先写测试，确认失败后再实现）⚠️

- [ ] T012 [P] [US2] 在 tests/unit/test_upload_validation.py 写 PCAP 上传校验测试（对照 contracts/rest-api.md POST /api/upload/pcap）：扩展名白名单 .pcap/.pcapng/.cap（大小写不敏感）、>100MB 拒绝（413 语义）、空文件名拒绝（400）、成功时 file_path 形如 data/uploads/<8位前缀>_<原名>。先跑一次确认现状失败（当前无服务端校验）
- [ ] T013 [P] [US2] 在 tests/unit/test_defaults_endpoint.py 写默认值接口测试（对照 contracts/rest-api.md GET /api/experiment/defaults）：返回 experiment.json 的 target_ip/max_iters/no_improve_limit；配置修改后（测试内临时写读）重启进程读取生效。先跑一次确认现状失败（接口尚不存在）

### 用户故事 2 的实现

- [ ] T014 [US2] 在 backend/server.py 实现上传服务端校验（G3）：扩展名白名单 + 100MB 上限 + 结构化错误响应（400/413，错误文案按 contracts/rest-api.md）；校验失败不落盘；成功响应含 file_path/file_name/size_bytes（007-3 决议、FR-015/FR-016）。依赖 T012 测试先行
- [ ] T015 [US2] 在 backend/server.py 实现默认值单一来源（G4）：新增 `GET /api/experiment/defaults`（启动时从 src/config/experiment.json 读取 target_ip/max_iters/no_improve_limit）；StartRequest 兜底默认改为同一来源；为 StartRequest 增加 max_iters/no_improve_limit ≥1 校验（data-model「实验运行」约束字段）。依赖 T013 测试先行
- [ ] T016 [US2] 在 frontend/app.js、frontend/index.html 接入默认值（G4 前端部分）：页面加载时请求 /api/experiment/defaults 填充表单初值，移除 index.html 中的硬编码 value（保留 placeholder）；start_experiment 收到 error（"实验已在运行中…"）时回滚运行态为就绪（G5 部分，FR-009 前端语义）
- [ ] T017 [US2] 在 tests/integration/test_status_stop.py 写状态/停止会话语义集成测试：GET /api/experiment/status 的 running 值与面板一致；POST /api/experiment/stop 受理后实验结束消息推送且状态复位（FR-017/FR-018、SC-008/009）

**检查点**: 用户故事 2 完整可用且可独立测试（quickstart 场景 2/3/4/7 通过）

## 阶段 5：用户故事 3 - 连接状态可视与断线容错（优先级：P3）

**目标**: 连接/实验状态徽章、断线不崩溃、错误提示明确、状态可查询

**独立测试**: quickstart.md 场景 1/7/8——连接徽章随状态变化、断线后服务与实验不受影响、无效消息收到错误提示、B 客户端隔离

### 用户故事 3 的测试（先写测试，确认失败后再实现）⚠️

- [ ] T018 [P] [US3] 在 tests/unit/test_ws_errors.py 写断线与错误消息测试：无效 JSON → error（"无效的 JSON"）；未知消息类型 → error（"未知消息类型: …"）且实验状态不变；WebSocketDisconnect 后会话标记断开、服务不崩溃、实验继续（FR-019/FR-020）

### 用户故事 3 的实现

- [ ] T019 [US3] 在 frontend/app.js 完善断线体验：ws.onclose 显示「未连接」徽章并给出「刷新页面重新连接」提示（可加一次自动重连尝试）；连接成功/断开文案对照 FR-003（含 client_id 展示）
- [ ] T020 [US3] 在 frontend/app.js、frontend/index.html 处理统计卡数据源（G5）：为「当前轮次/最佳 RTT/最近 RTT」确定数据来源（v1 从 tool_result/experiment_done 解析，解析不到时明确显示「暂未采集」而非常显 "-"）；依赖 T019（同文件 app.js，避免冲突）
- [ ] T021 [P] [US3] 在 frontend/index.html、frontend/style.css 增加「仅限可信内网使用」声明横幅（G1 前端部分；样式沿用暗色主题变量）

**检查点**: 用户故事 3 完整可用且可独立测试（quickstart 场景 1/7/8 通过）

## 阶段 6：打磨与横切关注点

**目的**: 影响多个用户故事的改进与最终收敛

- [ ] T022 [P] 在 README.md 增加 Web 控制台安全声明段落：仅限已授权可信内网、无认证说明、HITL 审批要求（007-1 决议；与现有「合规与安全声明」节衔接）
- [ ] T023 [P] 在 backend/server.py 增加启动日志输出内网限定警告（logging，一条 WARNING 级声明；007-1 决议）
- [ ] T024 在项目根执行 `uv run pytest tests/ -v` 全量回归；按 quickstart.md 8 个场景手工验收；对照 spec.md FR-001~FR-020 与 SC-001~SC-010 逐项打勾，未满足项记入收敛任务清单（宪法二）；复查宪法七项原则（重点：四 HITL 不可绕过、六 默认值单一来源）

## 依赖与执行顺序

### 阶段依赖

- **搭建（阶段 1）**: 无依赖，可立即开始（T003 可与 T001/T002 并行）
- **地基（阶段 2）**: 依赖搭建完成——阻塞所有用户故事（T004→T005→T006 串行）
- **用户故事（阶段 3–5）**: 依赖地基完成；按优先级 P1→P2→P3 顺序推进（US1 是 MVP；US2/US3 在地基后可与 US1 并行，若人手允许）
- **打磨（阶段 6）**: 依赖所有目标故事完成

### 每个用户故事内部

- 测试必须先写并确认失败，再实现（T007/T008/T011 → T009/T010；T012/T013 → T014~T016；T018 → T019/T020）
- 后端实现先于前端联调；核心实现先于集成
- 故事完成后再进入下一优先级

### 并行机会

- 阶段 1：T003 [P] 与 T001/T002 并行
- 阶段 3：T007、T008、T011 三个测试任务互不依赖（不同文件）可并行；测试齐备后 T009（backend）与 T010（frontend）可并行
- 阶段 4：T012、T013 测试并行；T014（backend 上传）与 T013 的接口实现互不冲突，可交错推进
- 阶段 5：T018（测试）与 T021（横幅，不同文件）可并行；T019→T020 串行（同文件 app.js）
- 阶段 6：T022、T023 并行

## 实施策略

### MVP 优先（仅用户故事 1）

1. 完成阶段 1：基线确认（backend 测试通路建立）
2. 完成阶段 2：地基（per-client_id 会话注册表——关键，阻塞所有故事）
3. 完成阶段 3：用户故事 1（观察 + 审批闭环）
4. **停下来验证**: 独立测试用户故事 1（quickstart 场景 1/5/6 + T007/T008/T011 全绿）
5. 可部署/演示

### 增量交付

1. 搭建 + 地基完成 → 会话模型就绪
2. 加用户故事 1 → 独立测试 → 部署/演示（MVP！）
3. 加用户故事 2 → 独立测试 → 部署/演示（上传校验 + 默认值单一来源）
4. 加用户故事 3 → 独立测试 → 部署/演示（断线容错 + 声明横幅）
5. 打磨 → 全量回归 + 收敛打勾

## 备注

- [P] 任务 = 不同文件、无依赖
- [USn] 标签把任务映射到用户故事以便追溯
- 每个用户故事应可独立完成、独立测试
- 实现前确认测试失败
- 每个任务或逻辑分组后提交
- 避免：含糊任务、同文件冲突、破坏独立性的跨故事依赖
- 本特性为回溯式：现状已实现部分（WS 消息类型、上传唯一文件名、前端三件套、状态/停止接口），任务只覆盖 plan.md 的 G1–G6 差距，不得重写无关逻辑
- 涉及与 008 联动的任务（T007/T009/T011 的统一审批结构）在 008 的 G3（三处 payload 统一）落地后应重跑一次 T007/T008 确认兼容
