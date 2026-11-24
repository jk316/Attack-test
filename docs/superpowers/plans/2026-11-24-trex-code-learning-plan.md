# TRex 代码学习基建 Implementation Plan

> 目标：把智能体对 TRex「API 用法」的知识来源从模型记忆换成仓库里的真实代码
> （官方客户端库签名 dump + 官方示例 vendor），实验床环境事实仍以
> `docs/trex-astf-playbook.md` 为准。本计划只含基建，不含并发 CPS 研发。

**Goal:** 让 DSH 会话智能体与项目实验 agent 在做 TRex 任务时能「从代码学」，
不再凭模型对 TRex 的模糊记忆反复踩坑。

**Spec:** 本文档即规划（用户批准范围：P0 + P1）。

## 状态

| 阶段 | 内容 | 状态 |
|------|------|------|
| P0 | 环境确认（SSH 149 / trex311 / trex-core 3.08 位置） | ✅ 完成 |
| P1 | API 探测脚本 + 生成 reference 文档 | ✅ 完成 |
| P2 | vendor 官方示例进仓库 | ⏸ 待批准 |
| P3 | asciidoc 文档转 markdown 语料（可选） | ⏸ 待批准 |
| P4 | DSH skill（trex 类） | ⏸ 待批准 |
| P5 | 项目 agent 提示词注入 playbook 3 条铁律 | ⏸ 待批准 |
| P6 | 验证（dry-run 生成质量 + astf_verify 回归签名） | ⏸ 待批准 |

## P0 环境事实（已实测确认，2026-11-24）

- TRex daemon：`10.99.80.222`，RPC sync=4501 / async=4502，**当前 ASTF 模式，
  version `v3.08`**（build 2025-11-05，探针 `--connect` 实测握手成功）。
- 客户端机器：`10.99.80.149`（root，本机 id_rsa 可直连）。
- 客户端库位置：`/root/fzx/Trex_Scripts/v3.08/automation/trex_control_plane/interactive/`
  （3.x 布局：`trex/stl/api.py`、`trex/astf/api.py`；**不是 pip 安装**，
  靠 `/root/.bashrc` 的 `PYTHONPATH` 注入；目录本身不是 git 仓库，
  stl 模块 VERSION=`git-archive.dev3047580162`）。
- 运行解释器：`/root/miniconda3/envs/trex311/bin/python`（Python 3.11.16，
  与 `experiment.json → trex.python` 一致）。
- 服务器上另有本项目副本 `/root/fzx/Attack-test`（未动）。
- 探针脚本与生成文档的落库位置：`scripts/trex_api_probe.py` →
  `docs/trex-api-reference.md`（161 行，已生成并核对）。

## P1 产物与验证

- 新增 `scripts/trex_api_probe.py`（仅 stdlib；无 trex 库的解释器优雅降级，
  退出码 1；`--connect` 用**子进程 + 15s 硬杀**防 TRex RPC 挂起；
  ASTF 客户端优先于 STL——实验床 daemon 是 ASTF 单实例）。
- 新增 `tests/unit/test_trex_api_probe.py`：10 用例全绿
  （本地 Windows 无 trex 库路径 + fake 模块渲染 + 子进程超时/成功路径）。
- `docs/trex-api-reference.md` 已核对 playbook §4.3 反例全部对上：
  `ASTFTCPClientTemplate(..., port=80, cps=1, cont=None, ...)`（参数名 `port` 非 `dport`）、
  `ASTFClient.start(..., pid_input='_', ...)`（无 `profiles` 参数）、
  `ASTFIPGenGlobal(ip_offset='1.0.0.0')`（默认即会偏移目标 IP——playbook 铁律的根源）、
  `ASTFProfile(..., cap_list=None)`（§8 待验证的 cap_list 姿势确实存在）。

### 探测中发现的新事实（建议回写 playbook，待批准）

1. **`ASTFProgram.recv(bytes, clear=False)` 没有 timeout 参数**：
   `scripts/astf_verify.py` / `astf_get_flood.py` 里的 `recv(1, 10000)` 实际把
   `10000` 传给了 `clear`（truthy → `clear=True`），并非 playbook 注释所说的
   「10 秒超时」。语义不同——**注释已修正（2026-11-24）**：`recv(bytes, clear=False)`
   的 `clear` 表示「达水位后清零流计数」，无超时参数；脚本调用本身保持不变
   （`clear=True` 对单发验证无影响）。
2. **3.08 客户端没有 `ASTFUDPClientTemplate` / `ASTFUDPServerTemplate`**：
   有状态 UDP 模板在本版本不可用（「未找到符号」节已收录）。
3. `ASTFProgram` 无 `close` / `get_var` / `wait_for_flow`；STL 客户端无
   `load_profile`（只有 ASTF 客户端有）。
4. daemon `mode='ASTF'`：STL 客户端连 ASTF daemon 会挂起（探针首版实测挂死），
   生成的 STL 脚本若要 live 跑需先确认 daemon 模式（或按 playbook §8 双实例方案）。

## 重跑配方（客户端库升级后重新生成 reference）

```bash
# 本机（Windows）上传并运行：
scp scripts/trex_api_probe.py root@10.99.80.149:/tmp/
ssh root@10.99.80.149 \
  'PYTHONPATH=/root/fzx/Trex_Scripts/v3.08/automation/trex_control_plane/interactive \
   /root/miniconda3/envs/trex311/bin/python /tmp/trex_api_probe.py \
   --expect 3.08 --connect 10.99.80.222:4501 -o /tmp/trex-api-reference.md'
scp root@10.99.80.149:/tmp/trex-api-reference.md docs/trex-api-reference.md
```

## 后续任务（待批准后再实施）

- [ ] **Task P2: vendor 官方示例** — 从 `/root/fzx/Trex_Scripts/v3.08/`
      拷 3-5 个最相关示例（`scripts/astf/`、`scripts/stl/`、
      `automation/trex_control_plane/interactive/trex/examples/astf/`）进
      `trex_examples/`，进 git；智能体「抄骨架改参数」。
- [ ] **Task P3（可选）: 文档语料** — trex-core `doc*/**` asciidoc 转 markdown
      摘要入 `docs/trex-api/`。
- [ ] **Task P4: DSH skill** — 按 writing-skills 规范创建 trex 类 skill：
      触发词 TRex/ASTF/`cat_*.py`/trex_scripts；要求先读 playbook +
      `docs/trex-api-reference.md` + `trex_examples/` + `trex_common.py`；
      固化验证签名 `tx=5/rx≥13` 与「并发 CPS 未跑通」限制。
- [ ] **Task P5: 项目 agent 提示词注入** — playbook §6 的 3 条铁律注入
      `src/prompts/trex_catalog_prompt.j2` 与 `system_prompt.j2`，指向
      `docs/trex-api-reference.md`（playbook §8 原待办）。
- [ ] **Task P6: 验证** — ① dry-run 让智能体生成 ASTF 脚本，检查不再犯
      §4.3 反例写法；② live 回归 `scripts/astf_verify.py` 签名
      `tx=5 / rx≥13`（需 HITL 批准）。

## 风险

- 客户端库树是 `git-archive.dev…` 快照（非 git 仓库）：升级时靠目录替换 +
  重跑探针；`--expect` 与 daemon `--connect` 版本是防漂移护栏。
- `--connect` 每次会与 daemon 建一次短连接（只读 version/system info，
  不 acquire 端口、不发流量）。
- 本计划不含并发 CPS 攻坚、不含模型微调、不改 daemon/trex-core 源码。
