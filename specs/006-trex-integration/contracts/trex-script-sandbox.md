# 契约：TRex 脚本沙箱（write_python_file）

**特性目录**: `specs/006-trex-integration/` | **日期**: 2026-11-19

**契约性质**: 描述 `write_python_file` 工具的外部行为契约。现状已实现并满足 FR-001/002/003；本契约同时是 `run_python_file` 输入的前置约束。

## 1. 输入

| 参数 | 类型 | 约束 |
|------|------|------|
| filename | string | 非空；匹配 `^[A-Za-z0-9][A-Za-z0-9._-]*\.py$`（纯文件名、无目录、无路径分隔符、无 `..`）；去 `.py` 后缀后不得为 Windows 保留名（CON/PRN/AUX/NUL/COM1-9/LPT1-9） |
| code | string | ≤100000 字符；≤2000 行 |

## 2. 落盘规则

- 目标路径固定为 `<项目根>/trex_scripts/<filename>`；目录不存在时自动创建。
- **即使语法检查失败，文件仍写入**（供人工检查修复）——语法结论与落盘解耦。
- 写入失败（OSError/ValueError）返回失败结果，不抛出异常。

## 3. 语法检查（仅解析，不执行）

- 对源码做 parse-only 检查；成功 → `syntax_ok=true`，失败 → `syntax_ok=false` + `syntax_error`（含行号，如 `invalid syntax (line 12)`）。
- 检查绝不执行任何代码、不产生任何副作用（FR-003）。

## 4. 返回契约

```json
// 成功（含语法错误仍返回 success=true，结论在 syntax_ok）
{"success": true, "path": "<root>/trex_scripts/cat_udp_flood.py", "filename": "cat_udp_flood.py", "syntax_ok": false, "syntax_error": "invalid syntax (line 12)"}
// 文件名非法
{"success": false, "error": "Invalid filename (must be a bare *.py name, no directories): '../evil.py'"}
// 规模超限
{"success": false, "error": "code exceeds 100000 chars"}
```

**不变量**: `success=false` ⇒ 未写入；`success=true` ⇒ 文件存在于沙箱目录；返回的 `path` 恒在 `trex_scripts/` 下。

## 5. 与探索模式的衔接

- 探索模式提示词要求 filename 以 `cat_` 开头；本工具不强制该前缀（约束在提示词层，FR-013）。
- 探索模式的达标统计（G1）与清理（G2）以沙箱目录内 `cat_*.py` 文件集合为对象，与本契约第 2 节落盘规则一致。
