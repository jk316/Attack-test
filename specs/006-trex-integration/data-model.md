# 数据模型：TRex 集成与攻击目录探索

**特性目录**: `specs/006-trex-integration/` | **日期**: 2026-11-19

实体来自 spec.md「关键实体」节，字段与校验规则以现状实现 + 计划缺口（G1–G4）为准。

## 实体 1：TRex 脚本（Script）

| 字段 | 类型 | 说明 |
|------|------|------|
| filename | string | 纯 `.py` 文件名（无目录）；探索模式必须 `cat_` 开头 |
| code | text | 完整源码；≤100000 字符且 ≤2000 行 |
| path | string | `<项目根>/trex_scripts/<filename>`（沙箱目录唯一落盘位置） |
| syntax_ok | bool | 仅解析（不执行）的语法检查结论 |
| syntax_error | string \| null | 语法错误信息（含行号） |
| detected_ips | list | 源码中全部点分十进制 IPv4 字面量 |
| suspicious | list | 非白名单、非 TRex 服务器地址、非环回的 IP（去重保序） |

**校验规则**: 文件名不匹配 `^[A-Za-z0-9][A-Za-z0-9._-]*\.py$` → 拒绝；去后缀后命中 Windows 保留名（CON/PRN/AUX/NUL/COM1-9/LPT1-9）→ 拒绝；规模超限 → 拒绝；写入失败（OSError）→ 返回错误。语法错误的脚本仍落盘（供人工检查修复，FR-003）。

## 实体 2：执行结果（Execution Result）

| 字段 | 类型 | 出现条件 | 说明 |
|------|------|---------|------|
| success | bool | 总是 | dry-run 下 = syntax_ok；live 下 = returncode==0 |
| mode | enum | 总是 | dry_run / live |
| path / filename | string | 总是 | 脚本定位 |
| syntax_ok / syntax_error | bool/string | 总是 | 语法检查结论 |
| detected_ips / non_allowlisted_ips | list | 总是 | 静态筛查结果 |
| returncode | int | live | 进程退出码 |
| stdout / stderr | string | live | 截断至 4000 字符（超出附 `…(+N chars)`） |
| elapsed_s | float | live | 执行耗时 |
| error | string | 失败时 | 超时/启动失败/非 0 退出/语法错误/可疑 IP/目标 IP 非法等分类 |
| rtt_during / attack_window / observation_window | dict | live 成功且提供 target_ip | RTT 观测（与 005 同构） |

## 实体 3：攻击目录条目（Catalog Entry）

对应一个 `cat_*.py` 脚本及其文档化元数据。

| 字段 | 说明 |
|------|------|
| 攻击名称 | 脚本头部注释块字段 |
| 攻击类别 | 同上（如 UDP 泛洪 / TCP 状态机 / 放大攻击） |
| 攻击机制 | 2–4 句中文，攻击原理与流量特征 |
| 关键参数 | `参数名=默认值` 逐行列表 |
| 预期效果 | 对目标的预期影响（RTT 升高/丢包/连接表耗尽/IDS 触发） |
| 脚本文件 | `cat_*.py` 文件名 |

**完整性规则**: 五个注释字段缺一即不满足 FR-014；目录总结按此结构输出表格。

## 实体 4：目录摘要（Catalog Summary）

| 字段 | 说明 |
|------|------|
| 表格 | 每行一个攻击：# / 攻击名称 / 类别 / 机制 / 脚本文件 / 关键参数 / 预期效果 |
| 能力边界总结 | 覆盖与未覆盖的攻击维度、TRex 表达手段（STL 字段工程 / ASTF 状态机 / 多流组合） |
| 落盘路径 | `output/trex_attack_catalog_<YYYYMMDD_HHMMSS>.md`（时间戳防覆盖，FR-018） |

## 实体 5：探索配置（Explore Config）

| 字段 | 默认 | 说明 |
|------|------|------|
| catalog_target | 10 | 最少达标脚本数（`--catalog-target`；G1 达标校验依据） |
| explore_direction | 空 | 自由文本探索方向（`--explore-direction`）；为空执行通用枚举 |
| max_iters | 40 | 迭代预算（探索模式专属默认） |
| clean_scripts | false | **G2 新增**：启动时清空 `trex_scripts/cat_*.py` |
| exit_code | 0/1 | **G1 新增**：探索结束达标 → 0；未达标 → 1（总结仍落盘） |

## 运行门控状态机（run_python_file）

```
调用(filename, target_ip?)
  → 文件名解析（非法 → 拒绝）
  → 存在性检查（缺失 → 拒绝，提示先写入）
  → target_ip allowlist（提供且非法 → 拒绝）
  → 读取 + 语法检查 + 静态 IP 筛查
  → [dry-run] 返回检查报告（零执行）                      ← 默认路径
  → [live] 语法错误 → 拒绝
  → [live] 存在可疑 IP → 拒绝并列出
  → [live] HITL 审批（拒绝 → 零执行）
  → subprocess 执行（timeout=(0,300]s）
       ├─ 超时 → 终止 + 超时结果
       ├─ 启动失败 → OSError 结果
       └─ 完成 → returncode/stdout/stderr/elapsed（+RTT 观测若 target_ip）
```

## 探索模式生命周期（main.py）

```
解析参数（互斥校验：--trex-explore ∧ --trex-live → 报错退出）
  → [G2] --clean-scripts → 删除 cat_*.py
  → 强制 TREX_DRY_RUN=true、注入 CATALOG_TARGET/EXPLORE_DIRECTION
  → graph(mode="catalog")：仅 TREX_TOOLS + trex_catalog_prompt.j2
  → Agent 循环（规划 → 批量生成 cat_*.py → 语法校验重试 → 达标或预算耗尽）
  → 最终总结落盘 output/trex_attack_catalog_<ts>.md（FR-018/021）
  → [G1] 统计 cat_*.py 语法通过数 → 决定退出码（≥target → 0；否则 1）
```
