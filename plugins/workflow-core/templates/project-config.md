<!--
推荐在项目里运行 /workflow-core:init 自动探测并生成本小节；也可以手动复制到项目根目录的 AGENTS.md（或 CLAUDE.md）后按实际填写。
workflow-core 的各技能会到这里取路径和命令；不适用的项写“无”，未确认的写“待确认”，不要留示例值。
-->

## 工作流配置（ai-dev-workflow）

- 产品文档根：`docs/product/`（项目首页：`docs/product/项目首页.md`）
- 需求说明：`docs/product/需求/需求说明.md`
- 任务卡目录 / 总览：`docs/product/任务/` / `docs/product/任务/版本任务总览.md`
- 设计索引：`docs/product/设计/<设计工具>设计关联.md`
- 工程规范：`docs/development/` 下的 coding / architecture / ui / api-integration / testing
- 规格工具：OpenSpec（`openspec/`）｜无
- 交接目录：有变更时 `openspec/changes/<change-id>/handoff.md`；否则 `docs/development/handoffs/<task-id>.md`
- 验证命令：
  - 文档：workflow-core 文档规范检查（`check_docs.py`，由技能调用）；项目另有文档检查时写出命令，如 `<命令>`
  - 轻量：`<定向测试 + 静态分析命令>`
  - 标准：`<完整检查命令>`
  - 完整：`<完整检查 + 构建命令>`
- 默认验证平台：<例：Android；iOS 仅在用户明确要求时执行>
- 设计工具：<Pixso / Figma / 无>，权威文件：<链接或文件 key>
- 接口工具：<Apifox 项目「名称」，项目 ID 位置 / 无>
- 代码产物要求：<例：新增/修改的自定义函数需中文文档注释；生成代码不手改>
- 项目额外约定：<只写本项目特有、换项目就不成立的规则>
