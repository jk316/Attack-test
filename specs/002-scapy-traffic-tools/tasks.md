# 任务：Scapy 流量工具集

**输入**: 来自 `specs/002-scapy-traffic-tools/` 的设计文档

**前置**: [plan.md](./plan.md)（必需，差距 G1–G7）、[spec.md](./spec.md)（用户故事来源，必需）、[research.md](./research.md)（决策 D1–D6）、[data-model.md](./data-model.md)、[contracts/traffic-spec-json.md](./contracts/traffic-spec-json.md)、[contracts/tool-result-json.md](./contracts/tool-result-json.md)、[quickstart.md](./quickstart.md)

**组织方式**: 任务按用户故事分组，使每个故事可独立实现与测试。项目已存在（回溯式计划），阶段 1 为基线确认；实现任务 = 现状 → 规格差距（plan.md「实施工作清单」）。编号按文档顺序升序。

## 任务总览

| 任务 ID | 阶段 | 所属故事 | 可并行 | 说明 |
|---------|------|---------|--------|------|
| T001 | 1 搭建 | — | 否 | 跑通现有测试基线 |
| T002 | 1 搭建 | — | P | 对照契约核对现状差异 |
| T003 | 1 搭建 | — | P | 核对上限常量与宪法一致 |
| T004 | 2 地基 | — | 否 | 参数校验/拒绝矩阵单测锁定 |
| T005 | 2 地基 | — | P | ping_rtt 行为单测锁定 |
| T006 | 2 地基 | — | P | log_tool 行为单测锁定 |
| T007 | 2 地基 | — | P | 混合规格校验单测锁定 |
| T008 | 3 US1 | US1 | P | 钳制标注单测（先写测试，红） |
| T009 | 3 US1 | US1 | P | 截断标注单测（先写测试，红） |
| T010 | 3 US1 | US1 | P | traffic_send HITL 门控单测 |
| T011 | 3 US1 | US1 | 否 | traffic_send 钳制标注实现（G1） |
| T012 | 3 US1 | US1 | 否 | traffic_send 截断标注实现（G3） |
| T013 | 3 US1 | US1 | 否 | 多流轮转集成测试 |
| T014 | 4 US2 | US2 | P | 抖动参数化单测（先写测试，红） |
| T015 | 4 US2 | US2 | 否 | mixed 抖动参数化（G2） |
| T016 | 4 US2 | US2 | 否 | Agent 封装与提示同步 |
| T017 | 4 US2 | US2 | 否 | mixed 钳制/截断标注同步（G1/G3） |
| T018 | 4 US2 | US2 | 否 | mixed 加权随机集成测试 |
| T019 | 4 US2 | US2 | P | mixed HITL 门控单测 |
| T020 | 5 US3 | US3 | 否 | ping/log Agent 封装单测 |
| T021 | 5 US3 | US3 | P | ping+log 集成测试 |
| T022 | 5 US3 | US3 | 否 | ping/log 契约最小修复 |
| T023 | 6 打磨 | — | 否 | docstring 陈旧上限修复（G4） |
| T024 | 6 打磨 | — | P | 文档真实性更新 |
| T025 | 6 打磨 | — | 否 | 全量测试与覆盖率门禁 |

## 格式：`[ID] [P] [故事] 描述`

- **[P]**: 可并行（不同文件、无依赖）
- **[故事]**: 所属用户故事（US1/US2/US3）
- 描述中包含确切文件路径

## 阶段 1：搭建（基线确认——项目已存在）

**目的**: 建立回归基线并确认契约与现状的差距（plan.md 差距表 G1–G7 的核对基准）

- [x] T001 在项目根运行 `uv run pytest tests/unit/ -v` 与 `uv run pytest tests/integration/ -v`，记录通过/失败清单作为回归基线；任何既有失败记录到本任务说明（不在此修复与 002 无关的失败）——基线（001 完成后状态，bash .dsh/run-tests.sh tests/unit/ tests/integration/ -q）：**427 passed / 9 failed**；9 个失败与 001 基线完全一致（17 工具过期断言×2 + test_pktgen_client.py 直连真实 Pktgen 被 RST×7），与 002 无关，前置事实
- [x] T002 [P] 对照 `specs/002-scapy-traffic-tools/contracts/tool-result-json.md` 与 `contracts/traffic-spec-json.md` 核对 `src/tools/traffic_send_tool.py`、`src/tools/mixed_traffic_tool.py`、`src/tools/ping_rtt_tool.py`、`src/tools/log_tool.py`、`src/agent/tools.py` 的现状返回结构，产出差异清单记录到本任务说明（重点确认：`requested_params`/`clamped` 缺失、`completed`/`interrupt_reason` 缺失、mixed 无 `iat_jitter_ms` 参数；不修改代码）——差异清单：①traffic_send：requested_params/clamped 缺失（G1）、completed/interrupt_reason 缺失（G3）→ T011/T012 实现；②mixed：无 iat_jitter_ms 参数（固定 ±20ms 抖动，G2）、无四标注字段 → T015/T017 实现；③ping_rtt：契约 §4 全丢包 inf/loss100 ✅、超时 "Ping timeout expired" ✅、命令缺失 "ping command not found" ✅ 均已实现；非 allowlist 现状为 validate_target 抛 ValueError（契约写「success:false + 校验错误」）→ T022 最小修复候选；④log_tool：契约 §5 全部一致（追加、UTC ISO8601、父目录缺失 "Directory does not exist" 不建文件、msg "日志写入成功"）；⑤agent/tools.py：traffic_send 封装 HITL + 五个 ATK_* env 默认解析已实现；mixed 封装无 iat_jitter_ms（T016 补）
- [x] T003 [P] 核对 `src/tools/traffic_send_tool.py` 的 `MAX_PPS=20000/MAX_DURATION_S=20/MAX_PACKET_SIZE=1024/MAX_FLOW_COUNT=100/MAX_IAT_JITTER_MS=20` 与 `src/tools/mixed_traffic_tool.py` 的 `MAX_STREAMS=100/MAX_JSON_LENGTH=10000` 与 `specs/002-scapy-traffic-tools/plan.md` 及宪法「参数上限」一致（记录结果，不修改）——全部一致 ✅；观察：mixed 重复定义 MAX_PPS/MAX_DURATION_S/MAX_IAT_JITTER_MS（未从 traffic_send_tool 导入，存在漂移风险），记录不修改

---

## 阶段 2：地基（阻塞性前置）

**目的**: 以测试锁定既有安全与校验行为（allowlist 拒绝矩阵、钳制、规格校验、ping/log 语义），为后续改动提供回归保护

**⚠️ 关键**: 本阶段完成前不得开始任何用户故事工作

- [x] T004 在 `tests/unit/test_traffic_send_tool.py` 核对并补齐 `src/tools/traffic_send_tool.py::validate_params` 单测（data-model「校验规则汇总」FR-002–006）：越限钳制矩阵（pps=999999→20000、duration=999→20、packet_size=4096→1024、flow_count=500→100、jitter=100→20）、非正数与负抖动拒绝、dst_port 0/65536 拒绝、src_ip 非空拒绝；`validate_target` 拒绝矩阵（非 allowlist 192.168.1.99、广播 x.x.x.255、组播 224.x、格式非法、allowlist 为空拒绝一切）——新增 TestValidationMatrix 8 用例（dst_port 0/65536、packet_size/flow_count=0、负 duration、非法 IP 格式、validate_params 纯函数钳制矩阵）；既有 25 用例覆盖钳制/拒绝/组播/广播/空 allowlist；全绿
- [x] T005 [P] 在 `tests/unit/test_ping_rtt_tool.py` 锁定 `src/tools/ping_rtt_tool.py` 行为（FR-015、SC-007）：全丢包 → `avg_rtt_ms=inf` 且 `loss_pct=100`、命令缺失 → `success=false`、超时 → 失败、非 allowlist → 拒绝；`build_ping_cmd` 在 win32/非 win32 两平台参数断言（跨平台，不硬编码）——新增 TestPingCommandBuilding（win32 "-n/-w"、unix "-c/-W"）+ TestPingErrorPaths（FileNotFoundError→"ping command not found"、TimeoutExpired→"Ping timeout expired"、全丢包 inf/100）7 用例；既有 10 用例保持；全绿（15）
- [x] T006 [P] 在 `tests/unit/test_log_tool.py` 锁定 `src/tools/log_tool.py` 行为（FR-016、SC-008）：追加单行合法 JSON、`timestamp` 为 UTC ISO 8601、两次调用追加不覆盖、父目录不存在 → `success=false` 且不创建文件——新增 2 用例（timestamp 以 +00:00 结尾、父目录缺失不创建文件）；既有 9 用例已覆盖追加/roundtrip/字段完整性；全绿（11）
- [x] T007 [P] 在 `tests/unit/test_mixed_traffic_tool.py` 锁定 `src/tools/mixed_traffic_tool.py` 规格校验行为（FR-010–013、SC-005）：白名单外协议/空协议栈/流数 0 与 101/重复 stream_id/`percentage` 非整数或越界/总和不为 100/显式之和 ≥100 无法补齐/超长 >10000 字符/注入模式（`__import__`、`eval(`、`os.`、`open(` 等）各断言拒绝并含原因；`percentage` 缺失时平均补齐（含余数 +1 分支）；`build_packet_template` 的 IP.dst 强制覆盖断言（FR-011）——新增 7 用例（percentage 0/101 拒绝、eval(/open( 注入、余数 33/33/34 与整除 25×4 补齐）；既有 36 用例覆盖其余矩阵；全绿（43）

**检查点**: 既有安全行为全部被测试锁定——用户故事可以开始实现

---

## 阶段 3：用户故事 1 - 实验员发送受控单协议 UDP 流量（优先级：P1）🎯 MVP

**目标**: `traffic_send` 增加钳制感知（requested_params/clamped）与截断标注（completed/interrupt_reason）；多流轮转与 HITL 门控被测试锁定。

**独立测试**: 仅用 traffic_send 工具函数 + mock 网络即可验证：钳制标注字段、截断标注字段、轮转计数、HITL 拒绝 0 报文，不依赖 mixed/ping/log。

### 用户故事 1 的测试（先写测试，确认失败后再实现）⚠️

> **注意：先写测试，确认失败后再实现**

- [x] T008 [P] [US1] 在 `tests/unit/test_traffic_send_tool.py` 新增钳制标注单测（红，G1、002-1、FR-004、SC-001）：pps=999999 调用 → `params.pps=20000`、`requested_params.pps=999999`、`clamped` 含 `"pps"`；全合规调用 → `clamped` 为空列表；多字段越限 → `clamped` 含全部字段名（契约 `contracts/tool-result-json.md` §1；T011 完成后转绿）——红证据：6 用例全失败（KeyError requested_params/clamped、ImportError _clamped_fields）；T011 后全绿；全程 mock raw socket（MagicMock 内存内，零真实流量）；duration 钳制标注经纯函数 `_clamped_fields` 验证（避免 20 秒真实发送循环）
- [x] T009 [P] [US1] 在 `tests/unit/test_traffic_send_tool.py` 新增截断标注单测（红，G3、002-3、FR-008）：mock 发送循环中途抛 `KeyboardInterrupt` → 结果 `completed=false` 且 `interrupt_reason="keyboard_interrupt"`、`packets_sent` 保留已发部分；正常完成 → `completed=true` 且无 `interrupt_reason`（T012 完成后转绿）——红证据：KeyError completed/interrupt_reason；T012 后全绿
- [x] T010 [P] [US1] 在 `tests/unit/test_tools_hitl.py` 为 `src/agent/tools.py::traffic_send` 封装写单测（FR-009/017、SC-003）：审批拒绝 → `{"success": false, "error": "HITL rejected by operator"}` 且不调用底层发送；默认参数从 env（ATK_DURATION_S/ATK_PPS/ATK_PACKET_SIZE/ATK_FLOW_COUNT/ATK_IAT_JITTER_MS）读取、未注入回退内置默认——5 用例全绿（拒绝不调底层、payload message+params、批准透传、env 五参数、内置回退 10/100/64/1/0）

### 用户故事 1 的实现

- [x] T011 [US1] 在 `src/tools/traffic_send_tool.py` 实现钳制标注（G1、002-1）：返回结构新增 `requested_params`（原请求值）与 `clamped`（被钳制字段名列表，空 = 未钳制）；实现方式允许在 `validate_params` 返回钳制信息或调用处对比请求/实际值生成，HITL 展示仍用实际值（依赖 T008 红-绿闭环）——钳制前捕获 requested_params，纯函数 `_clamped_fields(requested, params)` 对比生成；HITL 展示（agent/tools.py）仍用解析后实际值，不受影响
- [x] T012 [US1] 在 `src/tools/traffic_send_tool.py` 实现截断标注（G3、002-3）：发送循环的 `except KeyboardInterrupt` 分支记录中断标记，最终结果 `completed=false` + `interrupt_reason="keyboard_interrupt"`；正常路径 `completed=true`（依赖 T009 红-绿闭环）——`completed` 恒入结果；`interrupt_reason` 仅中断时附加（正常完成无该键）
- [x] T013 [US1] 在 `tests/integration/test_traffic_send_flows.py` 写集成测试（FR-007、SC-004）：mock 网络下 flow_count=N（如 5）→ `per_flow` 覆盖 N 条流、任意两流计数差 ≤1、源端口互异（1024+序号）、`effective_pps` 计算正确、`send_mode` ∈ {raw, udp, scapy}；若现有等价测试存在则核对补齐（依赖 T011、T012 完成）——2 用例全绿（raw 路径捕获字节校验 5 端口 + scapy 回退路径；均 mock 网络零真实流量）

**检查点**: 用户故事 1 应完整可用且可独立测试（MVP）

---

## 阶段 4：用户故事 2 - 实验员模拟多协议混合业务流量（优先级：P2）

**目标**: `mixed_traffic_send` 抖动参数化（0–20 可配置、默认读 env）、同步钳制/截断标注、加权随机占比与 HITL 门控被测试锁定。

**独立测试**: 仅用 mixed_traffic_send 工具函数 + mock 网络即可验证：iat_jitter_ms 参数生效与钳制、标注字段、占比偏差、IP.dst 覆盖与 HITL 拒绝，不依赖 US1/US3 的其余行为（标注字段语义复用 T011/T012 定型结果）。

### 用户故事 2 的测试（先写测试，确认失败后再实现）⚠️

- [x] T014 [P] [US2] 在 `tests/unit/test_mixed_traffic_tool.py` 新增抖动参数化单测（红，G2、002-2、FR-014）：`iat_jitter_ms=5` 生效、`99` 钳制为 20、`-1` 拒绝、未传时读 env `ATK_IAT_JITTER_MS`（未注入回退 0）、`params.iat_jitter_ms` 返回实际值（契约 `contracts/tool-result-json.md` §3；T015 完成后转绿）——红证据：5 用例全失败（TypeError 未知名参数 / KeyError）；T015 后全绿
- [x] T015 [US2] 在 `src/tools/mixed_traffic_tool.py` 实现抖动参数化（G2、002-2）：`mixed_traffic_send_tool` 增加 `iat_jitter_ms: int | None = None`（None → 读 env `ATK_IAT_JITTER_MS`、缺省 0），钳制 0–20 后替换固定 ±`MAX_IAT_JITTER_MS` 抖动；配置落点 `src/config/experiment.json` 的 `attack.iat_jitter_ms`（键已存在，只需确认无需改文件）；返回 `params` 含 `iat_jitter_ms`（依赖 T014 红-绿闭环）——**R4（Lead 裁定）：注入补齐归属 002**——main.py parse_args 暴露 `args.iat_jitter_ms`（配置链 attack.iat_jitter_ms / profile 感知、无新 CLI 参数），新增 `_inject_attack_env()` 注入 `ATK_IAT_JITTER_MS`；tests/unit/test_config_chain.py 新增 TestJitterConfigInjection 3 用例锁定
- [x] T016 [US2] 在 `src/agent/tools.py` 的 `mixed_traffic_send` 封装同步 `iat_jitter_ms` 参数（env 默认解析与 `params_display` 展示）；在 `src/prompts/system_prompt.j2`「混合流量工具」参数表补充 `iat_jitter_ms` 说明（注明与 001-agent-core 的提示文件协调，只改混合工具参数表相关行）——封装签名/底层透传/docstring（顺带修 max 20/20000）/params_display 四处同步；提示混合工具参数表新增 `iat_jitter_ms` 行
- [x] T017 [US2] 在 `src/tools/mixed_traffic_tool.py` 同步钳制与截断标注（G1/G3 在 mixed 的落地）：返回结构增加 `requested_params`/`clamped`/`completed`/`interrupt_reason`，语义与 `contracts/tool-result-json.md` §3 一致（依赖 T011/T012 已定型的字段语义；与 T015 同文件，按顺序执行）——requested_params 在钳制前捕获（含 dst_ip/duration_s/pps/iat_jitter_ms）、clamped 对比三钳制字段、KeyboardInterrupt→completed=false+interrupt_reason；新增 TestMixedAnnotations 4 用例
- [x] T018 [US2] 在 `tests/integration/test_mixed_traffic_send.py` 写集成测试（FR-014、SC-005/006）：mock 网络下加权随机占比（≥10000 报文各流占比与声明偏差 ≤5 个百分点）、`per_stream` 计数、`raw_socket` 标记、百分比补全后 `params.streams` 与发送一致（依赖 T015、T017 完成）——3 用例全绿（60/40 偏差 ≤5pp、三流补全 33/33/34 且 per_stream 键一致、单流 100%）；pps=20000+duration=2s 达 ≥10000 包（MagicMock 开销限制实际速率）
- [x] T019 [P] [US2] 在 `tests/unit/test_tools_hitl.py` 追加 `src/agent/tools.py::mixed_traffic_send` 封装单测：审批拒绝 → 0 报文且不调用底层发送；`params_display` 含 dst_ip/duration_s/pps（FR-009）——3 用例全绿（拒绝不调底层、payload 四字段含 iat_jitter_ms、jitter env 默认解析）

### 用户故事 2 的实现

（T015/T016/T017 已完成，见「用户故事 2 的测试」节上方同号条目；T018/T019 亦完成）

**检查点**: 混合流量可独立验证，不依赖 US3

---

## 阶段 5：用户故事 3 - 实验员探测 RTT 并留存每轮实验日志（优先级：P3）

**目标**: `ping_rtt` 与 `log_result` 的 Agent 封装与端到端组合被测试锁定，并按契约做最小修复。

**独立测试**: 直接调用 ping_rtt/log_result（含 Agent 封装层）验证字段契约与 JSONL 落盘，无需发送任何流量。

- [x] T020 [US3] 在 `tests/unit/test_agent_tools_wrappers.py` 为 `src/agent/tools.py::ping_rtt` 与 `::log_result` 封装写单测（FR-015/016 的 Agent 层契约）：ping_rtt 透传底层返回；log_result 组装 `{iteration, params, rtt, loss}` 后调用 `src/tools/log_tool.py::log_tool`（mock 验证 entry 内容）——4 用例全绿（透传+kwargs、默认 count/timeout、entry 组装、entry 内容）
- [x] T021 [P] [US3] 在 `tests/integration/test_ping_log_e2e.py` 写集成测试（SC-007/008）：mock subprocess 输出 Unix 与 Windows 两种 ping 格式断言解析结果；`log_tool` 两次追加后逐行 `json.loads` 可解析且含 `timestamp`——4 用例全绿（Unix/Windows 解析、全丢包 inf、ping→log 闭环两行 UTC 时间戳）
- [x] T022 [US3] 在 `src/tools/ping_rtt_tool.py` 与 `src/tools/log_tool.py` 对照 `contracts/tool-result-json.md` §4/§5 核对字段并最小修复（如字段缺失/命名偏差），保持既有行为不变（G7；依赖 T020/T021 暴露偏差）——核对结果：log_tool 与 §5 完全一致无改动；ping_rtt 非 allowlist 现状抛 ValueError 与契约 §4「success:false + 校验错误」形状不符 → 最小修复：validate_target 的 ValueError 转为 `{"success": false, "error": str(e)}` 返回（安全语义不变——仍拒绝且不探测，subprocess 不被调用），同步更新既有 5 个拒绝矩阵测试为契约形状

**检查点**: 探测与日志可独立验证

---

## 阶段 6：打磨与横切关注点

**目的**: 文档真实性（FR-018）、端到端验证、全量回归门禁

- [x] T023 在 `src/agent/tools.py` 修复 docstring 陈旧上限（G4、FR-018、SC-009）：`traffic_send`/`mixed_traffic_send` 的 @tool 描述中 `max 200/10/512/50` 改为 `20000/20/1024/100`，`duration_s` 描述「max 10」改「max 20」，并补 `iat_jitter_ms` 描述；核对 `src/prompts/system_prompt.j2` 参数边界表已为正确值（依赖 US1/US2 完成，避免与新参数描述冲突）——traffic_send docstring 上限四字段修正 + Returns 补 requested_params/clamped/completed；mixed docstring 已在 T016 修正；grep 复核无残留陈旧值；提示边界表渲染自 MAX_* 常量已正确
- [x] T024 [P] 更新文档真实性：`CLAUDE.md`「Parameter Limits」「Important Constraints」中「Tool docstrings are stale」段落在修复后标注为已修复，并补充钳制标注/截断标注/抖动配置的行为描述（不涉及行为代码）——CLAUDE.md 三条更新：①「Tool docstrings are stale」→「Tool docstrings：已修复（002）」；②新增「钳制/截断标注」行为段；③新增「混合流量抖动」配置段（ATK_IAT_JITTER_MS 配置链注入）；Key Files 表 traffic_send_tool/mixed_traffic_tool 行同步更新
- [x] T025 运行全量门禁：`uv run pytest tests/unit/ -v`、`uv run pytest tests/integration/ -v`、`uv run pytest --cov=src --cov-report=term-missing`，确认全部通过且无既有基线回归；按 `specs/002-scapy-traffic-tools/quickstart.md` 场景 A/B/C 逐场景验证并把结果对照 SC 判据表记录到本任务说明——实测：`bash .dsh/run-tests.sh tests/unit/ tests/integration/ tests/e2e/ --cov=src` → **506 passed / 9 failed**（9 个与基线完全一致：17 工具断言×2 + Pktgen 直连×7，无新增回归；相对 002 基线 427P 净增 79）；覆盖率 TOTAL 87%。场景验证（安全红线优先：quickstart 场景 A 的直接脚本命令会发真实流量/真实 ping，**未执行**，改用等价安全验证）：A→mock 网络工具级测试（38 个 traffic 单测+2 集成+3 mixed 集成）+ 安全 CLI 冒烟（`-m` 形式非 allowlist 拒绝、无流量；log_tool 追加两行 UTC 时间戳 ✅）；发现：`python src/tools/traffic_send_tool.py` 直接脚本运行因相对导入失败（预存在，`-m` 模块形式正常），已记录待报 Lead；B→tests/unit 全绿；C→tests/unit/test_tools_hitl.py + 001 的 test_hitl_cli（HITL 链路 mock）；SC 对照：SC-001→test_traffic_send_tool 钳制矩阵、SC-002→拒绝矩阵、SC-003→test_tools_hitl、SC-004→test_traffic_send_flows、SC-005→test_mixed_traffic_tool 43 用例、SC-006→test_mixed_traffic_send ≥10000 包 ≤5pp、SC-007→test_ping_rtt_tool 15 用例、SC-008→test_log_tool 11 用例、SC-009→docstring 一致性（T023）

---

## 依赖与执行顺序

### 阶段依赖

- **搭建（阶段 1）**: 无依赖，可立即开始（T002/T003 可与 T001 并行）
- **地基（阶段 2）**: 依赖 T001 基线；阻塞所有用户故事（改动前的回归保护）
- **用户故事（阶段 3/4/5）**: 依赖地基完成；按优先级 P1 → P2 → P3 推进（US2 的 T017 依赖 US1 的 T011/T012 定型的标注字段语义）
- **打磨（阶段 6）**: 依赖三个故事全部完成（T023 尤其依赖 US1/US2）

### 每个用户故事内部

- 测试先写并确认失败，再实现（T008→T011、T009→T012、T014→T015）
- 核心实现先于集成（US1：T011/T012 先于 T013；US2：T015/T017 先于 T018）
- 故事完成并独立验证后再进入下一优先级

### 并行机会

- 阶段 1：T001 ∥ T002 ∥ T003
- 阶段 2：T004 与 T005/T006/T007 可并行（四个测试文件互不依赖）
- US1：T008、T009、T010 互相独立可并行；T011/T012 依赖各自测试先行
- US2：T014 与 T019 可并行；T016 在 T015 完成后可与 T017 并行推进
- US3：T020 与 T021 可并行（不同测试文件）
- 打磨：T024 可在 T023 完成后并行

## 实施策略

### MVP 优先（仅用户故事 1）

1. 完成阶段 1（T001–T003）：基线 + 契约差异清单
2. 完成阶段 2（T004–T007）：既有安全行为测试锁定
3. 完成阶段 3（T008–T013）：用户故事 1
4. **停下来验证**: 以 T013 + T010 独立测试 US1，对照 SC-001–004
5. 可演示：`uv run python src/tools/traffic_send_tool.py 10.99.80.160 8080 100 2` 返回含 `requested_params`/`clamped`/`completed` 的完整契约结果

### 增量交付

1. 基线 + 地基 → 安全行为锁定
2. 加 US1 → 独立测试 → MVP 可演示
3. 加 US2 → 独立测试 → 混合流量抖动可配置
4. 加 US3 → 独立测试 → 探测与日志闭环
5. 打磨（T023–T025）→ 文档真实性与全量门禁通过

## 备注

- [P] 任务 = 不同文件、无依赖
- [故事] 标签把任务映射到用户故事以便追溯
- 每个用户故事应可独立完成、独立测试
- 实现前确认测试失败（红-绿）；每个任务或逻辑分组后提交
- 同文件约束：`src/tools/traffic_send_tool.py` 的修改集中在 T011/T012（按顺序执行，不并行）；`src/tools/mixed_traffic_tool.py` 的修改集中在 T015/T017（顺序执行）；`src/agent/tools.py` 的修改集中在 T010/T016/T019/T020/T023（按阶段顺序执行）
- `src/config/experiment.json` 的 `attack.iat_jitter_ms` 键已存在（值 0），T015 只确认不修改；如 008-security-config 规格任务对该文件有并发修改，实施时需协调（共享任务板）
- 观测字段（rtt_during/attack_window/observation_window）结构由 003-ping-monitor-rtt 规格定义，本特性任务不修改其结构
- 避免：含糊任务、同文件冲突、破坏独立性的跨故事依赖
