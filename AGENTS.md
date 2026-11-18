# AGENTS.md — 本项目 SDD 工作流说明

本仓库采用 spec-kit 规格驱动开发（SDD）流程。每个功能走「规格 → 计划 → 任务 → 实现 → 收敛」的固定流程，由以下 9 个项目级工作流技能驱动（位于 `.dsh/skills/`，会话中按触发词调用）：

| 技能 | 一句话用途 |
|------|-----------|
| `speckit-constitution` | 确立/修订项目宪法（`.specify/memory/constitution.md`），每个项目只建立一次 |
| `speckit-specify` | 把自然语言需求写成功能规格 `spec.md`，生成特性编号并更新 `.specify/feature.json` |
| `speckit-clarify` | 针对现有规格提问澄清歧义，把答案回写进 `spec.md` |
| `speckit-plan` | 基于规格生成技术实现计划 `plan.md` 与设计制品（research / data-model / contracts / quickstart） |
| `speckit-checklist` | 生成需求质量检查清单 `checklist.md`——「需求层面的单元测试」 |
| `speckit-tasks` | 把设计制品拆成依赖有序、可直接执行的任务列表 `tasks.md` |
| `speckit-analyze` | 对 spec / plan / tasks 做跨制品一致性检查（只读），输出冲突、缺口、歧义报告 |
| `speckit-implement` | 按 `tasks.md` 的依赖顺序逐任务实现功能，自动勾选完成的任务 |
| `speckit-converge` | 实现完成后对照规格/宪法评估代码库，把剩余/偏差工作追加为任务 |

**当前特性目录**：记录在 `.specify/feature.json`（初始化后尚未创建任何特性，首个特性由 `speckit-specify` 生成）。

**分步触发约定**：每个技能一步一触发；每步结束必须汇报产物并提示下一步，不得跨技能自动连续执行。典型顺序：

```
constitution（一次性）→ specify → [clarify] → plan → [checklist] → tasks → [analyze] → implement → converge
```

## 项目上下文

<!-- 占位节：技术栈、目录结构、关键约定由 speckit-plan / speckit-implement 维护更新 -->

- 技术栈：Python 3.11+、Scapy、LangChain（LangGraph）、FastAPI、DeepSeek API；集成 Pktgen-DPDK（vendored Lua 编译器）与 TRex 客户端。
- 关键约定：所有流量工具强制 allowlist + HITL 审批；参数上限见 `.specify/memory/constitution.md`；配置单一来源为 `src/config/experiment.json`。
- 待更新：具体目录结构与模块边界由 speckit-plan 在规划特性时补充。
