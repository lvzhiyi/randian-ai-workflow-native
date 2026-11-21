# workflow-core 0.21.0 — 精简引擎入口、任务卡瘦身、自包含检查与归档技能

- **精简引擎 CLI 链路**：新增 `prepare`（自动从 `ai-workflow.yaml` 派生基线与检查计划、绑会话及发起定档）与 `begin`（核对人工定档/批准、批量输出全部必读基线正文并登记 SHA-256 回执、`start` 开工及可选 TDD）；`finish-step` 新增 `--finish-implementation`，写操作默认自动生成 `--request` 并内联返回 `progress` 投影，所有底层原子命令与硬门禁完整保留。
- **任务卡去数据库化与状态一致性硬拦截**：`templates/task-card.md` 收敛为 7 个核心业务字段（剔除与引擎/Git 重复的伪数据库元数据）；`check_docs.py` 移除 `负责人` 必填、简化结构化 `待确认` 校验，并新增勾选 `[x]` 与非终态协作状态冲突硬报错；`review_card.py` 拒绝回写已误勾 `[x]` 的卡片。
- **零第三方依赖自包含检查导出**：新增 `scripts/vendor_check_docs.py`，可将 `workflow_config.py` + `check_docs.py` 打包为单文件提交至消费项目 `scripts/check_docs.py`，脱离本机软链接与插件缓存。
- **变更归档闭环与轻骨架模式**：新增 `/workflow-core:archive` 技能与 `scripts/archive_change.py`（支持 `--dry-run` 预览、移动至 `archive/YYYY-MM-<id>/` 及自动断链检测，并在 `host_gate.py` 严格白名单放行）；新增单文件三合一工程规范模板 `templates/docs/development/standards.md`（≤200 行）。
- **技能与文档瘦身**：精简跨技能重复段落，并在 `README.md` 补充相对 Superpowers 的增强与优势说明。

升级后新建会话以加载更新后的技能、脚本与 hooks。
