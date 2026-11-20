# 阶段 0 研究：拨测监控生命周期收归程序

**特性**: `specs/009-auto-start-monitors/` | **日期**: 2026-11-20

每个条目按「决策 / 理由 / 备选方案」记录。

## R1 生命周期编排代码的位置

- **决策**: 新建 `src/tools/monitor_lifecycle.py`，提供 `start_experiment_monitors(target_ip, http_cfg=None)` 与 `stop_experiment_monitors()`，CLI 与 Web 控制台两个入口共同调用。
- **理由**: FR-001/FR-002 要求两个入口行为一致；设计文档定调「生命周期单一归属程序」；`ping_monitor.py` / `http_monitor.py` 各自只管理单个监控，编排跨两个单例，不应塞进其中任何一个。
- **备选**:
  - 两个入口各自内联重复实现——行为漂移风险，拒绝。
  - 编排放进 `ping_monitor.py` 或 `http_monitor.py`——职责混乱（一个模块管两个监控），拒绝。

## R2 Web 控制台入口的 HTTP 配置来源

- **决策**: `backend/experiment.py` 的 `ExperimentManager.start()` 直接读取项目根 `experiment.json` 的 `http` 段（与 `main.py` 的 `_load_config_defaults()` 同源，`CONFIG_PATH` 即项目根 `experiment.json`）；`http.url` 为空则不启动 HTTP 监控。
- **理由**: 前端 `app.js` 当前不发送 http 参数；宪法「配置单一来源」禁止为后端另设配置源；根 `experiment.json` 已是运行期配置的唯一来源。
- **备选**:
  - 前端表单新增 http 字段——改 UI + 前端状态，范围膨胀，拒绝。
  - 后端依赖环境变量——后端当前无注入点，需要新增设置逻辑，绕远，拒绝。

## R3 启动与清理的时机

- **决策**: main.py 在预检通过、env 注入之后、`graph.invoke()` 之前启动；在现有 `finally`（ping 清理处）扩展为同时停止 HTTP。后端在 `start()` 里 `_run_loop()` 之前启动；在 `start()` 的 `finally`（`_running=False` 处）停止。
- **理由**: 保证第一轮工具调用前监控已就绪（FR-001）；`finally` 覆盖正常结束、异常、中断三条退出路径（FR-007）。
- **备选**: 首次观测时懒启动——首轮基线必然缺失，违背 P1 用户故事，拒绝。

## R4 工具移除的范围

- **决策**: 从 `src/agent/tools.py` 整体删除 4 个函数（`start_ping_monitor` / `stop_ping_monitor` / `start_http_monitor` / `stop_http_monitor`）并移出 `EXPERIMENT_TOOLS`，工具总数 23 → 19。
- **理由**: spec 假设节已明确「非仅移出工具集，函数一并移除」，避免死代码与测试残留。
- **备选**: 保留函数仅移出列表——违背规格假设，拒绝。

## R5 失败降级与幂等

- **决策**: helper 内部 try/except + `logger.warning`；`validate_target` 校验失败仅告警不启动（FR-003 + FR-008）；启动前若监控已在运行则先 stop 再 start（幂等）。
- **理由**: 监控不可用不得阻断实验（SC-005）；Web 控制台连续启动两次实验时防止重复线程/子进程（规格边界情况）。

## R6 文案同步（提示词与结果提示）

- **决策**: `system_prompt.j2` 协议第 0 步改为「监控已由程序自动启动，直接读取基线」；删除结束时的 stop 指引；工具表删 4 行；`rtt_window.py` / `http_window.py` 的 note 文案与 `pktgen/adapter.py` 的 docstring 中「需先调用 start_ping_monitor」改为「监控由程序管理，不可用时按观测缺失处理」。
- **理由**: FR-009；防止模型调用已不存在的工具（宪法「文档真实性」）。
- **备选**: 只改提示词不改 note 文案——模型仍会读到自相矛盾的指引，拒绝。

## R7 trex-explore 目录模式豁免

- **决策**: main.py 在 `args.trex_explore` 为真时不调用 helper；helper 接受 mode 参数留扩展位。后端无目录模式，不受影响。
- **理由**: FR-004；目录模式零流量、无攻击窗口，监控无意义且浪费资源。

## R8 测试策略

- **决策**:
  - 更新工具数断言 23 → 19：`tests/integration/test_agent_graph.py::test_graph_has_23_tools`、`tests/integration/test_pktgen_integration.py::test_tool_count_is_23`（顺带改用例名）。
  - 改写引用 4 个工具名的既有用例：`tests/e2e/test_e2e_closed_loop.py`、`tests/integration/test_agent_graph.py`、`tests/integration/test_pktgen_integration.py`。
  - 新增 `tests/unit/test_monitor_lifecycle.py`：启动、清理、幂等重启、allowlist 拒绝、启动失败降级、http.url 为空不启动。
  - 新增集成用例：两个入口启动后监控自动运行（不依赖 Agent 调用）。
- **理由**: 宪法「测试伴随」（FR-011）；工具数断言是 SC-002 的可验证形式。
- **已知存量**: `tests/unit/test_llm_client.py` 有 8 个与本特性无关的既有失败（httpx 0.28.1 mock URL 解析，webui 分支同样存在），不在本特性范围内，验收时以「其余用例全绿 + 新增用例通过」为准。
