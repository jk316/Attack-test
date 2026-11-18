# 契约：TRex 运行门控链与探索达标（run_python_file / main.py）

**特性目录**: `specs/006-trex-integration/` | **日期**: 2026-11-19

**契约性质**: 描述 `run_python_file` 的门控链与结果契约（现状已实现，FR-005~011），以及探索模式达标与退出码契约（计划缺口 G1/G2 的目标口径）。

## 1. 门控链顺序（live 模式；dry-run 在语法/筛查后即返回）

| 步骤 | 失败行为 | 对应 FR |
|------|---------|---------|
| 1. 文件名解析 | `success=false, error=<原因>` | FR-001/004 |
| 2. 存在性 | `script not found: <path> (write it first)` | FR-004 |
| 3. target_ip allowlist | `success=false, error=<校验原因>`（格式/广播/组播/白名单） | FR-008 |
| 4. 读取 + 语法检查 + 静态 IP 筛查 | dry-run 直接返回报告；live 语法错误 → 拒绝 | FR-005/006/007 |
| 5. 静态 IP 筛查（live） | 含可疑 IP → 拒绝并列出 `non_allowlisted_ips` | FR-007 |
| 6. HITL 审批（live） | 拒绝 → `HITL rejected by operator`，零执行 | FR-009 |
| 7. subprocess 执行 | 超时/启动失败/非 0 退出 → 分类错误 | FR-010/011 |

**静态筛查口径**: 白名单 IP、TRex 服务器地址、`127.*` 豁免；筛查为 best-effort（混淆可绕过），HITL 为唯一硬边界（决策 006-1）。

## 2. HITL 审批材料（interrupt payload）

| 字段 | 内容 |
|------|------|
| message | `[HITL] Approve executing a generated Python script?` |
| params.filename / path | 脚本定位 |
| params.target_ip | 声明的目标 IP（可为空） |
| params.detected_ips | 源码中检测到的全部 IP 字面量 |
| params.code_preview | 源码前 500 字符 |
| params.warning | 现有：「此脚本将以本机当前用户完整权限执行任意 Python（无执行沙箱），请确认脚本内容。」＋ **G3 补充**：「脚本内 IP 静态筛查可被混淆绕过，请人工审查脚本内容。」 |

## 3. dry-run 报告契约

```json
{"success": true, "mode": "dry_run", "path": "...", "syntax_ok": true, "syntax_error": null,
 "detected_ips": ["10.99.80.160"], "non_allowlisted_ips": [],
 "message": "dry-run mode: script not executed."}
```

不变量：dry-run 返回绝不伴随子进程执行、审批事件或流量（SC-001）。

## 4. 执行结果契约（live）

| 场景 | 关键字段 |
|------|---------|
| 成功 | `success=true, returncode=0, stdout, stderr, elapsed_s, detected_ips`，提供 target_ip 时附 RTT 观测 |
| 非 0 退出 | `success=false, error="script exited with code N", stderr` |
| 超时 | `success=false, error="script timed out after {T}s", elapsed_s`；T 由 TREX_TIMEOUT_S 决定，钳制 (0,300]（默认 30） |
| 启动失败 | `success=false, error="failed to run script: ..."` |

输出截断：stdout/stderr 各 ≤4000 字符（超出附 `…(+N chars)`）。

## 5. 探索模式达标与退出码契约（G1/G2 目标口径）

| 项目 | 口径 |
|------|------|
| 达标判定 | 探索结束后对 `trex_scripts/cat_*.py` 逐文件做 parse-only 语法检查并计数（与工具口径一致，不执行） |
| 退出码 | 语法通过数 ≥ catalog_target → 0；未达标 → 1（非 0） |
| 总结落盘 | 无论达标与否，最终总结均写入 `output/trex_attack_catalog_<时间戳>.md`（FR-018/021） |
| 清理参数 | `--clean-scripts`：探索启动时仅删除 `trex_scripts/cat_*.py`（非 cat_ 文件绝不动），并在启动横幅打印；默认 False（决策 006-3） |
| 互斥 | `--trex-explore` 与 `--trex-live` 同时提供 → 解析期报错、进程以非 0 退出码终止（现状已实现，FR-020） |

## 6. 契约不变量（可测试口径）

1. dry-run 调用恒零执行、零审批、零流量（SC-001）。
2. 语法错误脚本 100% 在 live 被拦截（SC-003）。
3. 含非白名单 IP 字面量的脚本 100% 在 live 被拒绝并列出 IP（SC-004）。
4. 未审批的 live 请求 100% 零执行（SC-005）。
5. 超时终止偏差 ≤ +2s（SC-006）。
6. 探索未达标 → 退出码非 0 且总结已落盘（G1）；达标 → 退出码 0。
7. `--clean-scripts` 只影响 `cat_*.py`（G2）。
