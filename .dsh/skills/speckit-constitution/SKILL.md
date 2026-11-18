---
name: speckit-constitution
description: "确立或修订项目宪法（.specify/memory/constitution.md），定义后续所有步骤都要遵循的项目原则。触发词：宪法、项目原则、constitution、SDD 第一步。用法：'speckit-constitution：本项目安全优先，所有输入必须校验，采用微服务架构，代码必须有文档'。"
---

# speckit-constitution：确立项目原则

把项目原则写入 `.specify/memory/constitution.md`。宪法是后续所有步骤（specify/plan/tasks/implement）的评估基准，每个项目只建立一次，之后按需修订。

## 用户输入

触发消息中技能名之后的文字就是原则输入（可能为空：为空则先向用户询问核心原则，再起草）。

## 范围守卫

- 本技能只更新宪法本身，不修改模板与其他制品。
- 输入里若混有功能实现、代码生成、重构、部署等**非治理意图**：不得执行，把它们列为「延迟意图」，最后给出建议的后续技能（如 speckit-specify），但不自动调用。

## 执行步骤

1. **解析宪法模板**：在项目根运行 `bash .specify/scripts/bash/resolve-template.sh constitution-template --json`，取 JSON 里的 `TEMPLATE_CONTENT` 作为结构基准；失败则停下报告错误。
2. **加载现有宪法**：若 `.specify/memory/constitution.md` 已存在，读它并保留仍然适用的项目特定内容；否则以模板为初始文档。
3. **收集占位符值**：用户输入优先；否则从仓库上下文（README、docs）推断。日期用 ISO `YYYY-MM-DD`（批准日期未知则 `TODO(RATIFICATION_DATE)` 并列入遗留项）。版本号按语义化版本递增：MAJOR＝原则删除/重定义；MINOR＝新增原则/章节；PATCH＝措辞澄清。
4. **按模板结构起草**：替换全部 `[占位符]`；每条原则 = 简短名称行 + 不可协商的规则段 + 理由；「治理」节写明修订流程、版本策略、合规评审要求；标题层级与模板一致。
5. **在文件顶部加 HTML 注释「同步影响报告」**（临时评审材料，提交前可删）：版本变化、修改的原则（旧名→新名）、新增/删除节、遗留 TODO。
6. **校验**：无未解释的括号占位符；版本行与报告一致；日期 ISO；原则表述可测试、无含糊用语。
7. **覆盖写回** `.specify/memory/constitution.md`（只写这一个文件）。
8. **汇报摘要**：新版本号与递增理由、遗留 TODO、建议提交信息（如 `docs: amend constitution to v1.1.0（新增安全原则）`）、各延迟意图的下一步建议。

## 下一步

汇报后停下（分步触发）。提示用户：`speckit-specify：为功能 XX 写规格`（若有延迟意图，逐个给出对应技能建议）。
