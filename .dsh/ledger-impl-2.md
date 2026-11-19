# 恢复账本 — impl-second-half（005–008 + R7/R8 遗补）

工作目录: /Users/zxkkk/code/Attack-test/.dsh/worktrees/fbcdd24e（分支 worktree/fbcdd24e）
每完成一个任务追加一行: `[x] T0NN — 变更文件 — 测试结果`
每轮开工先读本账本 + tasks.md 勾选 + git log 决定续点。

## 基线记录（005-T001，2026-11-19 02:50）

- `bash .dsh/run-tests.sh tests/unit/ tests/integration/ -q` → **566 passed / 9 failed**（115s）。
  - 9 失败与 Lead 移交基线一致：① 2× 工具计数断言（test_agent_graph.py::test_graph_has_17_tools、test_pktgen_integration.py::test_tool_count_is_17，期望 17 现实 19）；② 7× test_pktgen_client.py（TestSendLua×3、TestExecuteLuaConvenience×1、TestConnectionErrors::test_connect_bad_host_raises、TestFullPipeline×2）。
  - 566 + 20(e2e) = 586，与 Lead 基线 586P/9F 吻合（e2e 单独进程跑不产生日志污染）。
- ⚠️ **全量单进程 `bash .dsh/run-tests.sh tests/ -q` 实测 578 passed / 17 failed**：多出 8 个
  tests/unit/test_verbose_callback.py 失败（TestChatModelStart×6、TestChatModelEnd×2）。
  根因（已定位，非我梯队回归）：e2e/integration 测试调用 src/main.py::main()，其日志初始化
  `logging.getLogger("agent").propagate = False` + addHandler(StreamHandler) 永久生效且不恢复；
  随后 caplog（依赖 root 传播）捕获不到记录 → assert 失败；旧 StreamHandler 写已关闭的
  pytest 捕获流报 "I/O operation on closed file"。单独跑该文件 9/9 绿。
  处置：已记账本并报 Lead（建议 tests/conftest.py autouse fixture 快照/恢复 "agent" logger
  或 main() 日志初始化幂等化），待裁定，不擅自扩范围。
- 环境：.venv Python 3.13.11；pyyaml 可用；pktgen_agent vendored 导入正常（adapter 测试全绿）。
- 网络实测：10.99.80.222:22022 TCP connect 成功但发送后 recv 被 reset（无可用 Pktgen）；
  192.0.2.1 在本网络可被 connect（网络劫持 TEST-NET，unroutable 假设失效）。

## 裁定 R9（Lead，2026-11-19 02:55）
- 同意修复 logger 测试污染：tests/conftest.py 加 autouse fixture，每测试前后快照/恢复
  "agent" logger 的 handlers/level/propagate（顺带保护 root level）；不改 main.py（propagate=False 有意设计）。
- 可并入 005 提交（commit 注明 R9）；全量门禁一律 `bash .dsh/run-tests.sh tests/ -q` 单进程。
- 批准 conftest 服务探测跳过方案 + bad_host 用例 mock 化 + test_pktgen_integration.py 17→19。
- 005 全量门禁通过口径：修复后仅剩 1 个既有失败（test_agent_graph.py 17 工具断言，归 006/008）。

## 任务账（005-pktgen-integration）


[x] T001 — 无变更 — 基线确认：unit+integration 566P/9F（=Lead 586-20 e2e）；全量单进程 578P/17F（多出 8 个 verbose_callback 污染失败，已报 Lead → R9 批准修复）；conftest 可用性检测仅 TCP connect，本机 10.99.80.222:22022 connect 成功但发送后 reset → 跳过误判为可用（T001 范围内修）
[x] T002 — 无变更 — Python 3.13.11 / pyyaml 6.0.3 / vendored pktgen_agent + execute 导入 OK / uv sync --extra dev 通过

[x] T003 — 只读核对（证据行号基于当前 src/pktgen/adapter.py，685 行）— 核对表见下
  已满足：RATE_LIMIT（YAML 编译期，证据：test_compile_error_on_invalid_params rate=999→CompileError）；
  ALLOWLIST（_SKILLS_WITH_DST_IP L96-99 + _apply_allowlist L217-227 + _run_traffic_tool L274-275）；
  HITL（_SKILLS_WITH_HITL L102-105 + _hitl_gate L230-243，dry-run 跳过 L236-237）；DRY_RUN 默认（is_dry_run L91-93）；
  等待封顶 60s（_wait_for_attack L208-214 min(duration,60000)）；RTT 观测（_sample_rtt L246-259 build_rtt_observation + mode）；
  错误分类（_build_summary L162-173）；产物审计（_normalize_result L138-159，lua_preview 200 截断）；
  pcap_replay 免 allowlist（不在 _SKILLS_WITH_DST_IP）；stats/stop 免 HITL（不在 _SKILLS_WITH_HITL）。
  缺口：G1 duration>60000 未拒绝（_execute_skill L176-205 无校验；仅等待封顶）→T007；
  G2 arp dst_ip 未过 allowlist（pktgen_arp_flood L424-467 仅把 dst_ip 用于 _sample_rtt L465-466）→T008；
  G3 src_ip 未拒绝（udp/tcp/icmp 签名 L296/L346/L390 透传 L331/L376/L416）→T009；
  D9 无 PKTGEN_SRC_IP（experiment.json pktgen 节仅 rate/duration_ms；main.py 仅注入 RATE/DURATION L553-554）→T004/T009；
  G4 工具默认硬编码 50/5000（L291-292 等）——消费实现归 008-G4，005 仅补验证测试 T012（阻塞至 008）；
  G5 replaced_mac 未进结果（packet_sequence 替换循环 L564-574 仅 logger.info）→T014/T016。
  D9 默认值决策：无仓库内真实源地址依据（allowlist 仅目标 10.99.80.160/100.1.11.x；无攻击机源文档），
  采用实验子网占位 10.99.80.10/24（区别于目标 .160 与 Pktgen .222），操作员可按实验拓扑改 experiment.json，
  测试全部 monkeypatch PKTGEN_SRC_IP 不依赖字面值；已列入 005 完成报告待 Lead 知悉。
[x] T004 — src/config/experiment.json（pktgen.src_ip=10.99.80.10/24）+ src/main.py（args.pktgen_src_ip + PKTGEN_SRC_IP 注入） — 注入链冒烟通过
[x] R9 — tests/conftest.py（autouse logger 快照/恢复） — e2e+verbose_callback 29P（原 8F 清零）
[x] 基线修复① — tests/integration/test_pktgen_integration.py（test_tool_count_is_17→19 并注明） — 30P/11S（pktgen_client+integration）
[x] 基线修复② — tests/integration/conftest.py（服务级探测：connect+发空命令+读响应，reset/超时即 skip）+ tests/integration/test_pktgen_client.py（bad_host 用例 monkeypatch socket.connect） — 30P/11S（硬件用例全部跳过，不再连真实设备）
[x] T005 — tests/unit/test_pktgen_safety_gates.py（新建 19 用例） — 红证据 13F（G1×4/G3×3/D9×6）；T007/T009 后全绿
[x] T006 — tests/unit/test_pktgen_adapter.py（+TestArpFloodDstIpAllowlist 3 用例） — 红证据 1F（arp 非白名单未拒）；T008 后全绿
[x] T007 — src/pktgen/adapter.py（DURATION_LIMIT_MS=60000 + _validate_traffic_params 接入 _run_traffic_tool 最前） — G1 用例绿
[x] T008 — src/pktgen/adapter.py（pktgen_arp_flood 提供 dst_ip 时 validate_target，ValueError→error dict） — G2 用例绿
[x] T009 — src/pktgen/adapter.py（udp/tcp/icmp 拒绝显式 src_ip + _configured_src_ip() env 优先回退配置默认填入参数） — G3/D9 用例绿
[x] T010 — 无变更 — US1 验证 85P（adapter 58 + safety_gates 19 + integration 部分）；dry-run 零流量、live 门控链无回归
[x] T011 — tests/unit/test_pktgen_adapter.py（+TestLiveWaitAndObservation 5 用例） — 等待封顶/观测字段与 mode 标注锁定，44P
[ ] T012 — 阻塞至 008-G4 完成（tasks.md 口径：实现归 008，本特性只补验证测试）
[x] T014 — tests/unit/test_pktgen_adapter.py（+TestReplacedMacDetail 3 用例） — 红证据 2F（replaced_mac 缺失）；T016 后全绿
[x] T015 — tests/unit/test_pktgen_skills_regression.py（新建 11 用例：range_scan 参数+allowlist、sequence 非法 JSON+转发、pcap 免 allowlist+HITL、stop/stats 免 HITL+dry-run 仅编译） — 全绿（现状即契约）
[x] T016 — src/pktgen/adapter.py（packet_sequence 收集 replaced_mac 明细进结果，仅替换时出现） — G5 用例绿
[x] T017 — 无变更 — US3 验证 77P（adapter+skills_regression+safety_gates）
[x] T018 — src/pktgen/adapter.py（9 工具 docstring 口径对齐：duration>60000 拒绝、arp dst_ip allowlist、src_ip 禁止、dry-run stop/stats 仅编译） — 无行为变更，相关测试保持绿
[x] T019 — src/prompts/system_prompt.j2（洪水表/运维表/参数语义/安全警告对齐；live 模式渲染不含 "dry-run" 字面以保回归测试不变式） — 3 个 prompt 渲染测试绿
[x] T020 — .dsh/verify-005-quickstart.py（新建验证脚本，不提交）/场景2 单测 — 场景1/3/4 全过、场景2 19P、场景5 依赖 008-G4 消费实现（记录）
      ⚠️ 规格偏差记录（待 Lead 裁定）：quickstart 场景3 预期「编译产物中该条目 MAC 为 topology dst_mac」——vendored 编译器对 seqTable 只发占位注释
      （"-- table data from $params.sequences..."），产物文件不含逐条目 MAC；D8 禁止改 vendored。适配器可观测行为（replaced_mac 明细 + executor
      params 级真实 MAC）已由单测锁定；quickstart.md 措辞是否需要修订待 Lead 裁定。
[x] T021 — 无变更 — 全量门禁 624P/1F/11S（仅剩 test_agent_graph.py::test_graph_has_17_tools，归 006/008；11 skip=无硬件 Pktgen 用例）；契约 §3/§5 六不变量逐条核对通过（新增拒绝路径均含 success+mode；HITL 拒绝 dict 缺 mode 与 §3 示例一致，属 008-G3 统一范围，已记录）
[x] commit c846824 feat(005) — 13 files, +838/-95

## 006-trex-integration
[x] T001 — 无变更 — 基线 test_trex_tools+test_trex_catalog_mode 40P/0F（全绿）
[x] T002 — 无变更 — uv sync 通过；topology.yaml yaml 读取可用；sys.executable 子进程可用
[x] T003 — 只读核对 — 契约核对表：sandbox 契约 §1-4 全部已满足（tools.py L42-75/L124-148：文件名正则+保留字、规模上限、语法失败仍落盘、parse-only 无副作用）；
  run-gates §1 门控链 7 步全部已满足（tools.py L263-310）；§3 dry-run 报告 ✓（L281-291）；§4 执行结果+截断+超时钳制 ✓（L99-104/L198-214/config.py L62-75）；
  §5 缺口：G1 达标计数/退出码缺失（main.py 收尾 L735-741 仅落盘）、G2 --clean-scripts 缺失、互斥 ✓（L306-310 parser.error）；§2 缺口：G3 warning 缺「静态 IP 筛查可被混淆绕过」提示（tools.py L184）
[x] T004 — 只读梳理 — main.py 修改位置清单：G1a 拒绝 → L310 互斥块后；--clean-scripts argparse → L298 后；G2 清理执行 → _run_preflight 后（L566 前，env 注入前）；G1b 达标统计+sys.exit → L741 后（catalog 落盘之后、try 块内，finally 仍会执行 ping 清理）
[x] T005 — tests/unit/test_trex_tools.py（+TestHitlPayloadWarningG3） — 红证据 1F（warning 缺 G3 提示）；T007 后全绿
[x] T006 — tests/unit/test_trex_config.py（新建 27 用例：timeout 钳制×8、host/port×7、dry-run×3、truncate×4 + 默认值） — 全绿（现状即契约）
[x] T007 — src/trex/tools.py（_execute_live 审批 warning 补「脚本内 IP 静态筛查可被混淆绕过，请人工审查脚本内容」，与既有完整权限警告并列） — G3 用例绿
[x] T008 — 无变更 — US1 验证 49P（trex_tools 22 + trex_config 27）；dry-run 零执行零审批不变
[x] T009 — tests/unit/test_trex_catalog_mode.py（互斥断言退出码非 0 + env 残留 false 强制回 true）+ test_trex_tools.py（dry-run 零审批断言） — 42P
[x] T010 — 无变更（手动验证） — 互斥 CLI 实测 exit=2 + 报错文案正确
[x] T011 — tests/unit/test_trex_catalog_exit.py（新建 12 用例：G1a 拒绝×2、计数×3、退出码×2、finalize×3、clean×3 含 flag 解析） — 红证据 12F（helpers 缺失）；T012/T013 后全绿
[x] T012 — src/main.py（--catalog-target<1 parser.error；_count_syntax_ok_catalog_scripts/_catalog_exit_code/_finalize_catalog_run；main() 返回退出码 + sys.exit(main())） — G1 用例绿
[x] T013 — src/main.py（--clean-scripts argparse + _clean_catalog_scripts + main() 探索分支清理横幅；仅 cat_*.py 不递归） — G2 用例绿
[x] T014 — 无变更 — test_trex_catalog_mode 20P + e2e 4P 全绿（渲染/互斥/工具集无回归）
[x] T015 — src/prompts/trex_catalog_prompt.j2（停止条件段补退出码/--clean-scripts 口径说明） — 提示词渲染测试绿
[x] T016 — tests/e2e/test_trex_explore_e2e.py（+6 用例：退出码 0/1/语法错误不计入 + clean-scripts 三态；fixture 把 get_trex_scripts_dir 指向 tmp_path 保证确定性）+ CLI 冒烟（--catalog-target 0 → exit 2、--help → 0） — 10P e2e；真实 LLM 场景按 R5 待密钥有效后补验
[x] R10 — specs/005-pktgen-integration/quickstart.md（场景 3 措辞修订为可观测事实：replaced_mac+params 级真实 MAC；vendored 编译器占位注释说明）
[x] T017 — 无变更 — 全量门禁 671P/1F/11S（唯一失败 test_agent_graph.py::test_graph_has_17_tools，归 008 清零）；run-gates §6 与 sandbox §5 不变量逐条核对通过（1-5 由既有测试锁定、6/7 新增测试锁定）
[x] commit 10a5ac9 feat(006) — 11 files, +502/-37

## 007-web-console（含 R7/R8 遗补）
[x] T001 — 无变更 — 基线：web 相关 5P（test_web_experiment）+ 全量 671P/1F/11S（唯一失败 test_agent_graph 17 工具断言，008 清零口径）
[x] T002 — tests/unit/conftest.py（新建 sys.path 显式声明） — backend 导入剥离代理后 OK（httpx InvalidURL 为宿主 no_proxy=[::1] 环境问题，run-tests.sh 已剥离）
[x] T003 — tests/unit/test_experiment_msg.py（新建 4 用例） — 4P（现状即契约，无缺口）
[x] T004 — backend/experiment.py（ExperimentSession + ExperimentManager per-client_id 注册表重构；approve/stop 所有者校验；审批决定每请求恰好消费一次；stop 优先注入拒绝值） — web 集成测试 5P + 会话单测绿
[x] T005 — backend/server.py（websocket_endpoint 传 client_id；hitl_response/stop_experiment 非所有者 → error "非会话所有者"；REST stop → stop_all()） — 测试绿
[x] T006 — tests/unit/test_experiment_sessions.py（新建 10 用例：注册表/互斥/所有者/恰好一次/stop 解锁/R7/R8） — 15P（含 web 5）
[x] R7（003-T018 遗补）— backend/experiment.py（start finally + 会话结束回调 _stop_ping_monitor/_on_session_end，多会话守卫：无其他会话运行才停单例监控）— 003 tasks T018 已勾注 R7；单测锁定
[x] R8（004-T017 遗补）— backend/experiment.py（pcap_path 非空时 pcap_profile_tool → profile_to_params（默认值取 experiment.json attack 节）→ user message 种子行；失败注入提示不中断）— 004 tasks T017 已勾注 R8；单测锁定
⚠️ 安全事件记录（2026-11-19 03:19，已报 Lead）：test_hitl_flow.py approve 用例初版 patch 生命周期缺陷 → 真实 traffic_send_tool 对 allowlist 目标约 10s 流量（pps=50）。已修复：patch 覆盖整个 start/approve 生命周期 + 测试内安全红线注释；修复后 0.89s 通过、mock 工具 1 次调用。
[x] T007 — tests/integration/test_hitl_flow.py（新建 2 用例：拒绝闭环/批准闭环；真实 build_graph+fake 模型+真实 interrupt） — 2P（mock 模型需同时实现 ainvoke；patch 生命周期覆盖整个实验——安全红线注释在案）
[x] T008 — tests/unit/test_experiment_stream.py（新建 4 用例：无遗漏顺序/类型映射/空态） — 全绿（现状即契约）
[x] T011 — tests/unit/test_hitl_semantics.py（新建 2 用例：approve(False)→Command(resume=False) + 工具层 HITL rejected 双栈断言） — 全绿
[x] T009 — backend/experiment.py 核对（_extract_hitl「dict 含 message」定位 + 全量透传 scope 兼容）+ test_experiment_stream.py +4 用例（scope 透传/无 scope 兼容/非 dict 忽略） — 31P 全绿
[x] T010 — frontend/app.js（审批弹窗 message+scope+params 明细 textContent 转义；拒绝展示核验通过；experiment_done summary 渲染 ≤2000 字符）+ style.css（.msg-summary） — 前端无测试框架，quickstart 手工验收覆盖
[x] T012 — tests/unit/test_upload_validation.py（新建 9 用例：白名单/大小写不敏感/400/413/不落盘/8位前缀） — 红证据 5F（无服务端校验）；T014 后全绿
[x] T013 — tests/unit/test_defaults_endpoint.py（新建 7 用例：默认值返回/兜底/loader 直读/≥1 校验） — 红证据 5F（接口不存在）；T015 后全绿
[x] T014 — backend/server.py（扩展名白名单 .pcap/.pcapng/.cap + 100MB 上限 + 400/413 结构化错误 + 校验失败不落盘 + 纯文件名防穿越） — 9 用例绿
[x] T015 — backend/server.py（GET /api/experiment/defaults 启动时读 experiment.json；StartRequest default_factory 同一来源；≥1 校验 400） — 7 用例绿
[x] T016 — frontend/app.js（loadDefaults() 拉取填充 + 启动被拒回滚运行态）+ frontend/index.html（移除硬编码 value 保留 placeholder） — 前端无测试框架，quickstart 场景 2/3/4 手工验收
[x] T017 — tests/integration/test_status_stop.py（新建 2 用例：status 反映 running；REST stop 终结 HITL 等待→结束推送+复位） — 2P
[x] T018 — tests/unit/test_ws_errors.py（新建 5 用例：无效 JSON/未知类型/状态不变/断线标记+服务存活/断线实验继续） — 5P（backend 断线容忍随 T004 落地，测试锁定 FR-019/020）
[x] T019 — frontend/app.js（ws 可变 + 自动重连一次复用 client_id + 重连失败刷新引导 + client_id 展示） — quickstart 场景 1/8 手工验收
[x] T020 — frontend/app.js（统计卡：tool_result 解析轮次/最佳/最近 RTT，解析不到显「暂未采集」+ 启动重置）+ index.html（初始「暂未采集」） — 手工验收
[x] T021 — frontend/index.html（.lan-banner 内网限定横幅）+ style.css（横幅样式 + body flex 适配） — 手工验收
[x] T022 — README.md（Web 控制台安全声明节：仅限可信内网/无认证/无自动批准路径/单客户端会话） — 文档
[x] T023 — backend/server.py（启动 WARNING 内网限定声明） — 冒烟见 T024
[x] T024 — 无变更 — 全量门禁 719P/1F/11S（唯一失败 test_agent_graph 17 工具断言，008 清零）；quickstart 场景 1/2/3/4/7 真实 HTTP 冒烟全过（横幅/默认值=experiment.json/上传成功与拒绝/≥1 校验/status），场景 5/6/8 由 mock 集成测试等价覆盖（真实 LLM 按 R5 待密钥后补验）；FR-001~020/SC-001~010 逐项打勾无缺口（60s 不自动放行=无超时自动批准路径，设计满足）
[x] commit e36eab5 feat(007) — 21 files, +1705/-112；R7/R8 遗补已随 003/004 tasks 勾注提交

## 008-security-config
[x] T001 — tests/integration/test_agent_graph.py（test_graph_has_17_tools→19 并注明，移交口径「008 清零」） — 基线全绿起跑
[x] T002 — tests/unit/test_target_validation.py（新建 7 用例：契约消息逐一断言） — 7P（现状即契约）
[x] T003 — tests/unit/test_limits_constants.py（新建 10 用例：宪法数值绑定） — 10P
[x] T004 — tests/integration/test_hitl_payload.py（新建 4 用例：三处 scope + mixed 流摘要 + trex warning） — 红证据 4F（scope 缺失/warning 缺声明）；T005-T007 后全绿
[x] T005 — src/agent/tools.py（traffic_send/mixed_traffic_send payload +scope:scapy_traffic；mixed params +stream_count/protocols 摘要） — 绿
[x] T006 — src/pktgen/adapter.py（_hitl_gate payload {message, params{skill,mode,...}, scope:pktgen_traffic}） — 绿
[x] T007 — src/trex/tools.py（payload +scope:trex_script；warning 追加「静态 IP 扫描为尽力而为，无法识别域名/拼接/编码构造的目标」） — 绿
[x] T008 — tests/unit/test_pktgen_duration_clamp.py（新建 3 用例）+ src/pktgen/adapter.py（_execute_skill 引擎边界钳制 ≤60000；与 005-G1 工具层拒绝分层共存，见账本裁定说明） — 绿
[x] T009 — tests/unit/test_gate_matrix.py（新建 7 用例：集合一致 + _hitl_gate payload 形状） — 绿
[x] T010 — tests/unit/test_mixed_src_ip.py（新建 6 用例）+ src/tools/mixed_traffic_tool.py（IP.src 字段拒绝，大小写不敏感；IP.dst 不拒因强制覆盖） — 绿（FR-004 伪造路径封堵）
[x] T011 — tests/unit/test_config_warning.py（新建 12 用例）+ src/main.py（_warn_config_over_limits：7 项逐项 WARN 字段/配置值/钳制上限，不退出；main() 预检后 env 注入前调用） — 绿
[x] T012 — tests/unit/test_pktgen_env_defaults.py（新建 17 用例）+ src/pktgen/adapter.py（floods+range_scan 的 rate/duration 默认改调用时读 env PKTGEN_RATE/PKTGEN_DURATION_MS，回退签名默认 50/5000；sequence/replay 保留 100 语义默认不接 env——记录于完成报告） — 绿（005-G4 实现归属落地）
[x] T013 — tests/unit/test_profiles_precedence.py（新建 6 用例：CLI>profile>基础、未知 profile SystemExit 列名） — 绿（现状即实现）
[x] T014 — tests/unit/test_autoapprove_guard.py（新建 5 用例）+ src/main.py（--auto-approve×live 互斥 parser.error；explore×auto-approve 不误伤） — 绿
[x] T015 — tests/unit/test_autoapprove_marking.py（新建 2 用例：标记输出/resume=True/input 零触发；无 flag 走人工） — 绿（现状即实现）
[x] T016 — tests/integration/test_dryrun_no_traffic.py（新建 5 用例：Pktgen/TRex dry-run 零 interrupt 零执行；explore 工具集=2 + 真实 graph 全程零 interrupt） — 绿
[x] T017 — 核验（002 已修复） — src/agent/tools.py 两处 docstring 上限与常量一致（20000/20/1024/100/20），无需修改
[x] T018 — tests/unit/test_doc_consistency.py（新建 5 用例：docstring×常量×提示词 0 冲突 + 无残留旧口径） — 5P
[x] T019 — README.md（auto-approve 互斥说明、Pktgen duration 上限口径、门控矩阵 arp 注、统一审批结构说明）+ src/main.py（--auto-approve help 文案） — 文档
[x] 005-T012 回补 — tests/integration/test_config_pipeline.py（+test_pktgen_tool_consumes_env_defaults 消费断言 77/9999） — 7P；005 tasks 已勾注「008 完成后回补」
[x] 005-T013 回补 — 无变更（验证） — adapter+env_defaults+config_pipeline+pktgen_client 全绿（pktgen_client 硬件用例 skip）
[x] T020 — 无变更 — 全量门禁 **809P/0F/11S 首次全绿**（基线 586P/9F → 809P/0F；9 个既有失败全部清零：17 工具断言×2 + pktgen_client×7）；CLI 安全路径冒烟（场景1 预检 exit1/场景5 互斥 exit2×2）；quickstart 场景 2/3/4/6/7/9 由单测/集成测试覆盖，场景 8 explore 真实 LLM 按 R5 待密钥后补验；FR-001~020/SC-001~010 收敛矩阵逐项打勾无缺口；宪法复查（四零豁免：auto-approve×live 互斥+统一审批+门控矩阵；六单一来源：PKTGEN env 链落地）通过

## 收官（2026-11-19 03:45）
- 全量门禁最终确认：809P/0F/11S（两次独立运行一致，提交后复验）。
- commits: c846824(005) 10a5ac9(006) e36eab5(007) f9f7112(008) 163d83e(chore 007-T024)
- 已向 Lead 发送收官报告（含 008 完成 + 四项决策记录 + 剩余待办）。

## Lead 最终验收（2026-11-19）
- 验收通过：005–008 共 82 任务 + R7/R8 遗补全部通过 Lead 独立复核。
- 终测：809P/0F/11S、覆盖率 90%、8 特性 177/177 勾选一致、提交链完整。
- S1 已记录并将于最终报告向用户如实披露；R5 真实 LLM 补验待 .env 密钥有效后由 Lead 再联系。
- 第二梯队正式收官。
