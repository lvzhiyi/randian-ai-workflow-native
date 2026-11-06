# 文档骨架模板

`init` 按需把这些模板复制到项目（默认 `docs/`），只创建缺失的文件，已有文件不覆盖。

- `{{...}}` 是占位符：生成时用探测到的事实替换；确实不知道的写「待确认」，不保留花括号。
- 指向未生成文档的链接，生成时删掉该行，避免产生坏链接。
- 以 `<!-- 说明：... -->` 开头的注释是给 AI 的填写说明，生成后删除。

| 模板 | 生成时机 |
| --- | --- |
| `product/项目首页.md`、`product/需求/需求说明.md`、`product/任务/版本任务总览.md` | init |
| `development/coding.md`、`architecture.md`、`testing.md` | init |
| `product/设计/设计索引.md` | init，项目有设计工具时 |
| `development/ui.md` | init，项目有界面时 |
| `development/api-integration.md` | init，项目有后端接口时 |
| 模块卡（`templates/task-card.md`） | prd-breakdown 首次拆出该模块时 |
| 交接记录（`templates/handoff.md`） | handoff 首次跨会话交接时 |
