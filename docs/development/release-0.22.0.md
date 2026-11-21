# SpecLock (workflow-core 0.22.0) — 开源品牌上线与新版双语实时看板

- **SpecLock 品牌重命名与 MIT 开源首页**：仓库主入口升级为英中双语文档（`README.md` / `README.zh-CN.md`），补充 `MIT` 开源协议并统一 `marketplace.json` 标识。
- **Dashboard 终态绿灯与 v0.21.0 新卡兼容**：
  - 修复 `dashboard_page.py` 中 `badge(state)` 缺失 `data-tone="good"` 映射的问题，`passed`、`review_passed`、`completed`、`ready`、`done` 终态统一展示绿灯徽章。
  - 扩充 `dashboard_data.py` 状态映射以兼容 `待处理`、`评审通过，待人工验收` 等精简任务卡协作状态，并允许结构化 `待确认` 仅保留 `待确认` / `影响` / `恢复条件` 三键（`负责人` 默认为 `未指定`，`来源` 可选）。
- **Dashboard 深色现代 UI 与门禁证据直出**：
  - 全新深色看板界面，每张任务卡直接展示 5 步阶段进度条（`Ready -> Implement -> Verify -> Review -> Done`）与三项实时门禁证据芯片（`Baselines SHA-256`、`Checks`、`Dual Review`），无需展开折叠区即可审阅关键门禁状态。
  - 新增 `?lang=en` 参数与右上角 `EN / 中文` 切换按钮（默认保持中文以兼容既有习惯）。
- **引擎列表与 Cursor 宿主自举修复**：
  - `workflow_engine_cli.py` 与 `session_binding.py` 新增 `list`（含 `--active`）只读任务列表命令，便于未绑定会话的 Agent 先发现已有活动任务再 `bind-executor` 或 `prepare`。
  - 修复 `cursor_gate.py` 中 `tool_input: None` 导致的异常，并在 `sessionStart` 直接输出已解析的 `workflow_engine_cli.py` 绝对路径（配合 `SKILL.md` 与 `host_gate.py` 提示引导），避免 Shell 中误用未展开的 `${CURSOR_PLUGIN_ROOT}`。

升级后新建会话以加载更新后的插件清单与脚本，刷新浏览器看板即可体验新版界面。
